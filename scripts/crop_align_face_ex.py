import argparse
import glob
import os
from pathlib import Path

import cv2
import numpy as np
import PIL
import PIL.Image
import scipy
import scipy.ndimage

from basicsr.utils.download_util import load_file_from_url

try:
    import dlib
except ImportError:
    print("Please install dlib by running:" "conda install -c conda-forge dlib")

# download model from: http://dlib.net/files/shape_predictor_68_face_landmarks.dat.bz2
shape_predictor_url = "https://github.com/sczhou/CodeFormer/releases/download/v0.1.0/shape_predictor_68_face_landmarks-fbdc2cb8.dat"
ckpt_path = load_file_from_url(
    url=shape_predictor_url, model_dir="weights/dlib", progress=True, file_name=None
)
predictor = dlib.shape_predictor(  # type: ignore
    "weights/dlib/shape_predictor_68_face_landmarks-fbdc2cb8.dat"
)  # type: ignore


def get_landmark(filepath, only_keep_largest=True):
    """get landmark with dlib
    :return: np.array shape=(68, 2)
    """
    detector = dlib.get_frontal_face_detector()  # type: ignore

    img = cv2.imdecode(np.fromfile(filepath, dtype=np.uint8), cv2.IMREAD_COLOR)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)

    # img = dlib.load_rgb_image(filepath)

    dets = detector(img, 1)

    # Shangchen modified
    print("\tNumber of faces detected: {}".format(len(dets)))
    # if only_keep_largest:
    #     print('\tOnly keep the largest.')
    #     face_areas = []
    #     for k, d in enumerate(dets):
    #         face_area = (d.right() - d.left()) * (d.bottom() - d.top())
    #         face_areas.append(face_area)

    #     largest_idx = face_areas.index(max(face_areas))
    #     d = dets[largest_idx]
    #     shape = predictor(img, d)

    #     # print("Part 0: {}, Part 1: {} ...".format(
    #     #     shape.part(0), shape.part(1)))
    # else:
    for k, d in enumerate(dets):
        # print("Detection {}: Left: {} Top: {} Right: {} Bottom: {}".format(
        #     k, d.left(), d.top(), d.right(), d.bottom()))
        # Get the landmarks/parts for the face in box d.
        shape = predictor(img, d)
        # print("Part 0: {}, Part 1: {} ...".format(
        #     shape.part(0), shape.part(1)))

        t = list(shape.parts())
        a = []
        for tt in t:
            a.append([tt.x, tt.y])
        lm = np.array(a)
        # lm is a shape=(68,2) np.array
        yield lm


def align_face(filepath, out_path):
    """
    :param filepath: str
    :return: PIL Image
    """

    try:
        lme = get_landmark(filepath, only_keep_largest=False)
    except:
        print("No landmark ...")
        return

    for idx, lm in enumerate(lme):
        lm_chin = lm[0:17]  # left-right
        lm_eyebrow_left = lm[17:22]  # left-right
        lm_eyebrow_right = lm[22:27]  # left-right
        lm_nose = lm[27:31]  # top-down
        lm_nostrils = lm[31:36]  # top-down
        lm_eye_left = lm[36:42]  # left-clockwise
        lm_eye_right = lm[42:48]  # left-clockwise
        lm_mouth_outer = lm[48:60]  # left-clockwise
        lm_mouth_inner = lm[60:68]  # left-clockwise

        # Calculate auxiliary vectors.
        eye_left = np.mean(lm_eye_left, axis=0)
        eye_right = np.mean(lm_eye_right, axis=0)
        eye_avg = (eye_left + eye_right) * 0.5
        eye_to_eye = eye_right - eye_left
        mouth_left = lm_mouth_outer[0]
        mouth_right = lm_mouth_outer[6]
        mouth_avg = (mouth_left + mouth_right) * 0.5
        eye_to_mouth = mouth_avg - eye_avg

        # Choose oriented crop rectangle.
        x = eye_to_eye - np.flipud(eye_to_mouth) * [-1, 1]
        x /= np.hypot(*x)
        x *= max(np.hypot(*eye_to_eye) * 2.0, np.hypot(*eye_to_mouth) * 1.8)
        y = np.flipud(x) * [-1, 1]
        c = eye_avg + eye_to_mouth * 0.1
        quad = np.stack([c - x - y, c - x + y, c + x + y, c + x - y])
        qsize = np.hypot(*x) * 2

        # read image
        img = PIL.Image.open(filepath)

        output_size = 512
        transform_size = 4096
        enable_padding = False

        # Shrink.
        shrink = int(np.floor(qsize / output_size * 0.5))
        if shrink > 1:
            rsize = (
                int(np.rint(float(img.size[0]) / shrink)),
                int(np.rint(float(img.size[1]) / shrink)),
            )
            img = img.resize(rsize, PIL.Image.Resampling.LANCZOS)
            quad /= shrink
            qsize /= shrink

        # Crop.
        border = max(int(np.rint(qsize * 0.1)), 3)
        crop = (
            int(np.floor(min(quad[:, 0]))),
            int(np.floor(min(quad[:, 1]))),
            int(np.ceil(max(quad[:, 0]))),
            int(np.ceil(max(quad[:, 1]))),
        )
        crop = (
            max(crop[0] - border, 0),
            max(crop[1] - border, 0),
            min(crop[2] + border, img.size[0]),
            min(crop[3] + border, img.size[1]),
        )
        if crop[2] - crop[0] < img.size[0] or crop[3] - crop[1] < img.size[1]:
            img = img.crop(crop)
            quad -= crop[0:2]

        # Pad.
        pad = (
            int(np.floor(min(quad[:, 0]))),
            int(np.floor(min(quad[:, 1]))),
            int(np.ceil(max(quad[:, 0]))),
            int(np.ceil(max(quad[:, 1]))),
        )
        pad = (
            max(-pad[0] + border, 0),
            max(-pad[1] + border, 0),
            max(pad[2] - img.size[0] + border, 0),
            max(pad[3] - img.size[1] + border, 0),
        )
        if enable_padding and max(pad) > border - 4:
            pad = np.maximum(pad, int(np.rint(qsize * 0.3)))
            img = np.pad(
                np.float32(img), ((pad[1], pad[3]), (pad[0], pad[2]), (0, 0)), "reflect" # type: ignore
            ) # type: ignore
            h, w, _ = img.shape
            y, x, _ = np.ogrid[:h, :w, :1]
            mask = np.maximum(
                1.0
                - np.minimum(np.float32(x) / pad[0], np.float32(w - 1 - x) / pad[2]),
                1.0
                - np.minimum(np.float32(y) / pad[1], np.float32(h - 1 - y) / pad[3]),
            )
            blur = qsize * 0.02
            img += (
                scipy.ndimage.gaussian_filter(img, [blur, blur, 0]) - img
            ) * np.clip(mask * 3.0 + 1.0, 0.0, 1.0)
            img += (np.median(img, axis=(0, 1)) - img) * np.clip(mask, 0.0, 1.0)
            img = PIL.Image.fromarray(np.uint8(np.clip(np.rint(img), 0, 255)), "RGB")
            quad += pad[:2]

        img = img.transform(
            (transform_size, transform_size),
            PIL.Image.QUAD,
            (quad + 0.5).flatten(),
            PIL.Image.BILINEAR,
        )

        if output_size < transform_size:
            img = img.resize((output_size, output_size), PIL.Image.Resampling.LANCZOS)

        # Save aligned image.
        # print('saveing: ', out_path)
        out_path = Path(out_path)
        nfname = f"{out_path.stem}_{idx:04}.png"
        ofname = out_path.parent / nfname
        img.save(ofname)

    # return img, np.max(quad[:, 0]) - np.min(quad[:, 0])


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--in_dir", type=str, default="./inputs/whole_imgs")
    parser.add_argument("-o", "--out_dir", type=str, default="./inputs/cropped_faces")
    args = parser.parse_args()

    if args.out_dir.endswith("/"):  # solve when path ends with /
        args.out_dir = args.out_dir[:-1]
    dir_name = os.path.abspath(args.out_dir)
    os.makedirs(dir_name, exist_ok=True)

    img_list = sorted(glob.glob(os.path.join(args.in_dir, "*.[jpJP][pnPN]*[gG]")))
    test_img_num = len(img_list)

    for i, in_path in enumerate(img_list):
        img_name = os.path.basename(in_path)
        print(f"[{i+1}/{test_img_num}] Processing: {img_name}")

        out_path = Path(args.out_dir) / f"{Path(in_path).stem}.png"
        out_path = str(out_path)

        # out_path = os.path.join(args.out_dir, in_path.split("/")[-1])
        # out_path = out_path.replace('.jpg', '.png')
        align_face(in_path, out_path)
