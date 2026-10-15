/*
 * Host-side YUYV frame source for browser capture and native integration tests.
 * The file lives in the emulator's host filesystem, never in the guest image.
 * Publish complete frames with an atomic rename; existing reads keep their inode.
 *
 * SPDX-License-Identifier: GPL-2.0-or-later
 */

#include "qemu/osdep.h"
#include "qapi/error.h"
#include "qemu/module.h"
#include "qemu/option.h"
#include "qemu/timer.h"
#include "video/video.h"

#define TYPE_FRAME_FILE "videodev-frame-file"
OBJECT_DECLARE_SIMPLE_TYPE(FrameFile, FRAME_FILE)

struct FrameFile {
    Videodev parent_obj;
    char *path;
    char *frame;
    int64_t next_frame;
    unsigned width;
    unsigned height;
    unsigned fps;
};

static int frame_file_open(Videodev *vd, QemuOpts *opts, Error **errp)
{
    FrameFile *s = FRAME_FILE(vd);
    const char *path = qemu_opt_get(opts, "path");
    const char *mode = qemu_opt_get(opts, "mode");
    bool browser = mode && !strcmp(mode, "browser");

    if (!path || !*path) {
        vd_error_setg(vd, errp, "frame-file requires path=<host YUYV file>");
        return VIDEODEV_RC_INVAL;
    }
    if (mode && !browser && strcmp(mode, "standard")) {
        vd_error_setg(vd, errp, "frame-file mode must be standard or browser");
        return VIDEODEV_RC_INVAL;
    }
    /* Keep the native fixture mode; reduce browser work and stale frame queues. */
    s->width = browser ? 320 : 640;
    s->height = browser ? 240 : 480;
    s->fps = browser ? 2 : 10;
    s->path = g_strdup(path);
    return VIDEODEV_RC_OK;
}

static int frame_file_close(Videodev *vd, Error **errp)
{
    FrameFile *s = FRAME_FILE(vd);

    g_clear_pointer(&s->frame, g_free);
    g_clear_pointer(&s->path, g_free);
    return VIDEODEV_RC_OK;
}

static int frame_file_enum_modes(Videodev *vd, Error **errp)
{
    FrameFile *s = FRAME_FILE(vd);
    VideoFramesize *size;

    vd->nmodes = 1;
    vd->modes = g_new0(VideoMode, 1);
    vd->modes[0].pixelformat = QEMU_VIDEO_PIX_FMT_YUYV;
    vd->modes[0].nframesize = 1;
    vd->modes[0].framesizes = g_new0(VideoFramesize, 1);
    size = &vd->modes[0].framesizes[0];
    size->width = s->width;
    size->height = s->height;
    size->nframerate = 1;
    size->framerates = g_new0(VideoFramerate, 1);
    size->framerates[0].numerator = 1;
    size->framerates[0].denominator = s->fps;
    return VIDEODEV_RC_OK;
}

static int frame_file_stream_on(Videodev *vd, Error **errp)
{
    FRAME_FILE(vd)->next_frame = 0;
    return VIDEODEV_RC_OK;
}

static int frame_file_stream_off(Videodev *vd, Error **errp)
{
    return VIDEODEV_RC_OK;
}

static int frame_file_claim(Videodev *vd, Error **errp)
{
    FrameFile *s = FRAME_FILE(vd);
    int64_t now = qemu_clock_get_ns(QEMU_CLOCK_REALTIME);
    g_autoptr(GError) error = NULL;
    gsize length;

    if (now < s->next_frame) {
        return VIDEODEV_RC_UNDERRUN;
    }
    if (!g_file_get_contents(s->path, &s->frame, &length, &error)) {
        vd_error_setg(vd, errp, "cannot read camera frame: %s", error->message);
        return VIDEODEV_RC_ERROR;
    }
    if (length != s->width * s->height * 2) {
        g_clear_pointer(&s->frame, g_free);
        vd_error_setg(vd, errp, "expected %u bytes of %ux%u YUYV",
                      s->width * s->height * 2, s->width, s->height);
        return VIDEODEV_RC_INVAL;
    }
    vd->current_frame.data = (uint8_t *)s->frame;
    vd->current_frame.bytes_left = length;
    s->next_frame = now + NANOSECONDS_PER_SECOND / s->fps;
    return VIDEODEV_RC_OK;
}

static int frame_file_release(Videodev *vd, Error **errp)
{
    g_clear_pointer(&FRAME_FILE(vd)->frame, g_free);
    vd->current_frame.data = NULL;
    vd->current_frame.bytes_left = 0;
    return VIDEODEV_RC_OK;
}

static void frame_file_class_init(ObjectClass *oc, void *data)
{
    VideodevClass *vc = VIDEODEV_CLASS(oc);

    vc->open = frame_file_open;
    vc->close = frame_file_close;
    vc->enum_modes = frame_file_enum_modes;
    vc->stream_on = frame_file_stream_on;
    vc->stream_off = frame_file_stream_off;
    vc->claim_frame = frame_file_claim;
    vc->release_frame = frame_file_release;
}

static const TypeInfo frame_file_info = {
    .name = TYPE_FRAME_FILE,
    .parent = TYPE_VIDEODEV,
    .instance_size = sizeof(FrameFile),
    .class_init = frame_file_class_init,
};

static void frame_file_register(void)
{
    type_register_static(&frame_file_info);
}

type_init(frame_file_register);
