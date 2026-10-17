/* Exercise synchronous browser-runtime dispatch, not guest code or guest data.
 * This is a stress smoke test, not a deterministic reproduction of the lifetime
 * race fixed upstream in Emscripten #26582.
 * SPDX-License-Identifier: GPL-2.0-or-later
 */
#include <emscripten.h>
#include <pthread.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>

static void *run(void *arg)
{
    const int id = (intptr_t)arg;

    for (int i = 0; i < 50000; i++) {
        int value = MAIN_THREAD_EM_ASM_INT({ return ($0 * 17) ^ $1; }, id, i);
        if (value != ((id * 17) ^ i)) {
            abort();
        }
    }
    return NULL;
}

int main(void)
{
    pthread_t threads[4];

    for (intptr_t i = 0; i < 4; i++) {
        if (pthread_create(&threads[i], NULL, run, (void *)i)) {
            abort();
        }
    }
    for (int i = 0; i < 4; i++) {
        if (pthread_join(threads[i], NULL)) {
            abort();
        }
    }
    puts("PASS: 200000 synchronous runtime calls returned matching results");
    return 0;
}
