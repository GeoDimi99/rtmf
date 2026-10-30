/*
 * rtmo_cpu.h - CPU placement of the RTMO runtimes (plan section 05).
 *
 * The deploy-manager gives every container the cores {control} + task cores
 * and passes them as RTMO_CONTROL_CPU and RTMO_TASK_CPUS. Each runtime calls
 * rtmo_pin_control() as the first thing in main(): the control thread (and
 * every thread created afterwards, e.g. the gRPC or ZeroMQ I/O threads) runs
 * on the control core. Task threads get their own core when they are created.
 *
 * It logs one line that shows where the control thread ended up:
 *   rtmo-affinity thread=control expected=4 effective=4 allowed=4-7 task_cpus=5-7
 * "allowed" is the cpuset of the container, before pinning.
 *
 * Header-only, usable from C and C++; needs _GNU_SOURCE before <sched.h>.
 */
#ifndef RTMO_CPU_H
#define RTMO_CPU_H

#include <errno.h>
#include <sched.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#include "logger.h"

#define RTMO_DEFAULT_CONTROL_CPU 4   /* the core every runtime used before RTMO_CONTROL_CPU */

/* "4", "4-7", "4,6-7"; "none" for an empty set */
static inline void rtmo_format_cpus(const cpu_set_t *set, char *buf, size_t len)
{
    size_t used = 0;
    buf[0] = '\0';
    for (int cpu = 0; cpu < CPU_SETSIZE && used < len; cpu++) {
        if (!CPU_ISSET(cpu, set)) continue;
        int last = cpu;
        while (last + 1 < CPU_SETSIZE && CPU_ISSET(last + 1, set)) last++;
        int n = (last == cpu)
            ? snprintf(buf + used, len - used, "%s%d", used ? "," : "", cpu)
            : snprintf(buf + used, len - used, "%s%d-%d", used ? "," : "", cpu, last);
        if (n < 0) break;
        used += (size_t)n;
        cpu = last;
    }
    if (buf[0] == '\0') snprintf(buf, len, "none");
}

/* Pin the calling thread to RTMO_CONTROL_CPU and log the result; returns 0 on success. */
static inline int rtmo_pin_control(const char *component)
{
    int cpu = RTMO_DEFAULT_CONTROL_CPU;
    const char *env = getenv("RTMO_CONTROL_CPU");
    if (env && *env) {
        char *end = NULL;
        long v = strtol(env, &end, 10);
        if (end && *end == '\0' && v >= 0 && v < CPU_SETSIZE) cpu = (int)v;
        else log_message(LOG_WARN, component, "rtmo-affinity: invalid RTMO_CONTROL_CPU '%s', using %d", env, cpu);
    }

    cpu_set_t allowed, want, effective;
    CPU_ZERO(&allowed);
    sched_getaffinity(0, sizeof(allowed), &allowed);

    CPU_ZERO(&want);
    CPU_SET(cpu, &want);
    int rc = sched_setaffinity(0, sizeof(want), &want);
    int err = errno;

    CPU_ZERO(&effective);
    sched_getaffinity(0, sizeof(effective), &effective);

    char allowed_s[128], effective_s[128];
    rtmo_format_cpus(&allowed, allowed_s, sizeof(allowed_s));
    rtmo_format_cpus(&effective, effective_s, sizeof(effective_s));
    const char *tasks = getenv("RTMO_TASK_CPUS");

    int ok = (rc == 0 && CPU_COUNT(&effective) == 1 && CPU_ISSET(cpu, &effective));
    log_message(ok ? LOG_INFO : LOG_WARN, component,
                "rtmo-affinity thread=control expected=%d effective=%s allowed=%s task_cpus=%s%s%s",
                cpu, effective_s, allowed_s, tasks && *tasks ? tasks : "unset",
                rc == 0 ? "" : " sched_setaffinity: ", rc == 0 ? "" : strerror(err));
    return ok ? 0 : -1;
}

#endif /* RTMO_CPU_H */
