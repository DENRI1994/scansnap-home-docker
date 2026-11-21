#define _GNU_SOURCE
#include <arpa/inet.h>
#include <dlfcn.h>
#include <errno.h>
#include <ifaddrs.h>
#include <net/if.h>
#include <netinet/in.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/types.h>

static pthread_once_t init_once = PTHREAD_ONCE_INIT;

static int (*real_bind)(int, const struct sockaddr *, socklen_t) = NULL;
static int (*real_getifaddrs)(struct ifaddrs **) = NULL;
static ssize_t (*real_sendto)(int, const void *, size_t, int,
                              const struct sockaddr *, socklen_t) = NULL;
static ssize_t (*real_sendmsg)(int, const struct msghdr *, int) = NULL;
static ssize_t (*real_sendmsg64)(int, const struct msghdr *, int) = NULL;

static void init_syms(void) {
    real_bind = dlsym(RTLD_NEXT, "bind");
    real_getifaddrs = dlsym(RTLD_NEXT, "getifaddrs");
    real_sendto = dlsym(RTLD_NEXT, "sendto");
    real_sendmsg = dlsym(RTLD_NEXT, "sendmsg");
    real_sendmsg64 = dlsym(RTLD_NEXT, "__sendmsg64");
}

static int is_virtual_ifname(const char *name) {
    static const char *const prefixes[] = {
        "virbr", "docker", "br-", "veth", "cni", "tun", "tap"
    };
    if (!name) {
        return 0;
    }
    for (size_t i = 0; i < sizeof(prefixes) / sizeof(prefixes[0]); i++) {
        size_t len = strlen(prefixes[i]);
        if (strncmp(name, prefixes[i], len) == 0) {
            return 1;
        }
    }
    return 0;
}

static int is_udp_socket(int sockfd) {
    int sock_type = 0;
    socklen_t len = sizeof(sock_type);
    if (getsockopt(sockfd, SOL_SOCKET, SO_TYPE, &sock_type, &len) != 0) {
        return 0;
    }
    return sock_type == SOCK_DGRAM;
}

static int is_broadcast_ipv4(const struct in_addr *addr) {
    uint32_t ip = ntohl(addr->s_addr);
    return (ip & 0xffU) == 0xffU;
}

#define MAX_ARP_PEERS 256

static int read_arp_peers(struct in_addr *peers, int max_peers) {
    FILE *fp = fopen("/proc/net/arp", "r");
    if (!fp) {
        return 0;
    }

    char line[256];
    int count = 0;
    int first = 1;

    while (fgets(line, sizeof(line), fp) && count < max_peers) {
        if (first) {
            first = 0;
            continue;
        }
        char ip_str[64], hw_type[32], flags_str[32], hw_addr[32], mask_str[32], dev_str[64];
        if (sscanf(line, "%63s %31s %31s %31s %31s %63s",
                   ip_str, hw_type, flags_str, hw_addr, mask_str, dev_str) != 6) {
            continue;
        }
        if (is_virtual_ifname(dev_str)) {
            continue;
        }
        unsigned long flags = strtoul(flags_str, NULL, 0);
        if (flags == 0) {
            continue;
        }
        struct in_addr addr;
        if (inet_pton(AF_INET, ip_str, &addr) != 1) {
            continue;
        }
        uint32_t host_order = ntohl(addr.s_addr);
        if ((host_order & 0xffU) == 0xffU || (host_order & 0xffU) == 0U ||
            (host_order >> 24) == 127U || (host_order >> 28) == 0xeU) {
            continue;
        }
        peers[count++] = addr;
    }

    fclose(fp);
    return count;
}

static void fanout_sendto_52217(int sockfd, const void *buf, size_t len, int flags) {
    if (!real_sendto) {
        return;
    }
    struct in_addr peers[MAX_ARP_PEERS];
    int count = read_arp_peers(peers, MAX_ARP_PEERS);
    for (int i = 0; i < count; i++) {
        struct sockaddr_in dst;
        memset(&dst, 0, sizeof(dst));
        dst.sin_family = AF_INET;
        dst.sin_port = htons(52217);
        dst.sin_addr = peers[i];
        real_sendto(sockfd, buf, len, flags,
                    (const struct sockaddr *)&dst, sizeof(dst));
    }
}

static void fanout_sendmsg_52217(int sockfd, const struct msghdr *msg, int flags,
                                 ssize_t (*fn)(int, const struct msghdr *, int)) {
    if (!fn) {
        return;
    }
    struct in_addr peers[MAX_ARP_PEERS];
    int count = read_arp_peers(peers, MAX_ARP_PEERS);
    for (int i = 0; i < count; i++) {
        struct sockaddr_in dst;
        memset(&dst, 0, sizeof(dst));
        dst.sin_family = AF_INET;
        dst.sin_port = htons(52217);
        dst.sin_addr = peers[i];

        struct msghdr unicast_msg = *msg;
        unicast_msg.msg_name = &dst;
        unicast_msg.msg_namelen = sizeof(dst);
        unicast_msg.msg_control = NULL;
        unicast_msg.msg_controllen = 0;
        fn(sockfd, &unicast_msg, flags);
    }
}

static void holepunch_trigger_ports(int sockfd) {
    if (!real_sendto) {
        return;
    }
    static const char probe[4] = {'s', 's', 'N', 'R'};
    static const uint16_t ports[3] = {52217, 53220, 55265};
    struct in_addr peers[MAX_ARP_PEERS];
    int count = read_arp_peers(peers, MAX_ARP_PEERS);

    for (int i = 0; i < count; i++) {
        for (int j = 0; j < 3; j++) {
            struct sockaddr_in dst;
            memset(&dst, 0, sizeof(dst));
            dst.sin_family = AF_INET;
            dst.sin_port = htons(ports[j]);
            dst.sin_addr = peers[i];
            real_sendto(sockfd, probe, sizeof(probe), 0,
                        (const struct sockaddr *)&dst, sizeof(dst));
        }
    }
}

ssize_t sendto(int sockfd, const void *buf, size_t len, int flags,
               const struct sockaddr *dest_addr, socklen_t addrlen) {
    pthread_once(&init_once, init_syms);
    ssize_t res = real_sendto(sockfd, buf, len, flags, dest_addr, addrlen);

    int saved_errno = errno;
    if (res >= 0 && dest_addr != NULL && addrlen >= sizeof(struct sockaddr_in) &&
        dest_addr->sa_family == AF_INET && is_udp_socket(sockfd)) {
        const struct sockaddr_in *sin = (const struct sockaddr_in *)dest_addr;
        if (ntohs(sin->sin_port) == 52217 && is_broadcast_ipv4(&sin->sin_addr)) {
            fanout_sendto_52217(sockfd, buf, len, flags);
        }
    }
    errno = saved_errno;
    return res;
}

static ssize_t handle_sendmsg(int sockfd, const struct msghdr *msg, int flags,
                              ssize_t (*fn)(int, const struct msghdr *, int)) {
    ssize_t res = fn(sockfd, msg, flags);

    int saved_errno = errno;
    if (res >= 0 && msg != NULL && msg->msg_name != NULL &&
        msg->msg_namelen >= sizeof(struct sockaddr_in) &&
        ((const struct sockaddr *)msg->msg_name)->sa_family == AF_INET &&
        is_udp_socket(sockfd)) {
        const struct sockaddr_in *sin = (const struct sockaddr_in *)msg->msg_name;
        if (ntohs(sin->sin_port) == 52217 && is_broadcast_ipv4(&sin->sin_addr)) {
            fanout_sendmsg_52217(sockfd, msg, flags, fn);
        }
    }
    errno = saved_errno;
    return res;
}

ssize_t sendmsg(int sockfd, const struct msghdr *msg, int flags) {
    pthread_once(&init_once, init_syms);
    return handle_sendmsg(sockfd, msg, flags, real_sendmsg);
}

ssize_t __sendmsg64(int sockfd, const struct msghdr *msg, int flags) {
    pthread_once(&init_once, init_syms);
    return handle_sendmsg(sockfd, msg, flags,
                          real_sendmsg64 ? real_sendmsg64 : real_sendmsg);
}

int bind(int sockfd, const struct sockaddr *addr, socklen_t addrlen) {
    pthread_once(&init_once, init_syms);
    int res = real_bind(sockfd, addr, addrlen);

    int saved_errno = errno;
    if (res == 0 && addr != NULL && addrlen >= sizeof(struct sockaddr_in) &&
        addr->sa_family == AF_INET && is_udp_socket(sockfd)) {
        const struct sockaddr_in *sin = (const struct sockaddr_in *)addr;
        uint16_t port = ntohs(sin->sin_port);
        if (port == 53220 || port == 55265) {
            holepunch_trigger_ports(sockfd);
        }
    }
    errno = saved_errno;
    return res;
}

int getifaddrs(struct ifaddrs **ifap) {
    pthread_once(&init_once, init_syms);
    if (!real_getifaddrs) {
        errno = ENOSYS;
        return -1;
    }
    int res = real_getifaddrs(ifap);
    if (res == 0 && ifap != NULL && *ifap != NULL) {
        for (struct ifaddrs *cur = *ifap; cur != NULL; cur = cur->ifa_next) {
            if (is_virtual_ifname(cur->ifa_name)) {
                cur->ifa_flags &= ~(IFF_UP | IFF_RUNNING);
                if (cur->ifa_addr != NULL && cur->ifa_addr->sa_family == AF_INET) {
                    cur->ifa_addr->sa_family = AF_UNSPEC;
                }
            }
        }
    }
    return res;
}
