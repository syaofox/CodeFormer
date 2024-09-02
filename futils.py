import os

import cv2
import numpy as np


def imread_utf8(img_path, mode=cv2.IMREAD_COLOR):
    img_array = np.fromfile(img_path, dtype=np.uint8)
    if img_array is not None:
        img = cv2.imdecode(img_array, mode)
        if img is not None:
            img = cv2.cvtColor(img, mode)
            return img
    return None


def imwrite_utf8(img, img_path):
    # 确保目录存在
    dir_path = os.path.dirname(img_path)
    if not os.path.exists(dir_path):
        os.makedirs(dir_path)
    
    # 将图像编码为 JPEG 格式
    success, encoded_img = cv2.imencode('.png', img)
    if success:
        # 使用 np.tofile 写入文件
        encoded_img.tofile(img_path)
        return True
    return False