#!/usr/bin/env python3
# -*-coding:UTF-8 -*

import os
import sys

from datetime import datetime
from io import BytesIO
from PIL import Image
from PIL import ImageDraw

from pymisp import MISPObject

sys.path.append(os.environ['AIL_BIN'])
##################################
# Import Project packages
##################################
from lib.objects.abstract_object import AbstractObject
from lib.ConfigLoader import ConfigLoader
from packages import Date
# from lib import Language
# from lib.data_retention_engine import update_obj_date, get_obj_date_first

from flask import url_for

config_loader = ConfigLoader()
r_cache = config_loader.get_redis_conn("Redis_Cache")
r_object = config_loader.get_db_conn("Kvrocks_Objects")
baseurl = config_loader.get_config_str("Notifications", "ail_domain")
IMAGE_FOLDER = config_loader.get_files_directory('images')
config_loader = None

# SET x1,y1:x2,y2:x3,y3:x4,y4:extracted_text

class Ocr(AbstractObject):
    """
    AIL Message Object. (strings)
    """

    def __init__(self, id):
        super(Ocr, self).__init__('ocr', id)

    def exists(self):
        return r_object.exists(f'ocr:{self.id}')

    def get_content(self, r_type='str'):
        """
        Returns content
        """
        global_id = self.get_global_id()
        content = r_cache.get(f'content:{global_id}')
        if not content:
            dict_content = {}
            for extracted in r_object.smembers(f'ocr:{self.id}'):
                extracted = extracted.split(':', 4)
                x, y = extracted[0].split(',', 1)
                # get text line, y +- 20
                rounded_y = round(int(y) / 20) * 20
                if rounded_y not in dict_content:
                    dict_content[rounded_y] = []
                dict_content[rounded_y].append((int(x), int(y), extracted[-1]))

            content = ''
            l_key = sorted(dict_content.keys())
            for key in l_key:
                dict_content[key] = sorted(dict_content[key], key=lambda c: c[0])
                for text in dict_content[key]:
                    content = f'{content}      {text[2]}'
                content = f'{content}\n'

            # Set Cache
            if content:
                global_id = self.get_global_id()
                r_cache.set(f'content:{global_id}', content)
                r_cache.expire(f'content:{global_id}', 300)

        if r_type == 'str':
            return content
        elif r_type == 'bytes':
            if content:
                return content.encode()

    def get_date(self): # TODO
        return Date.get_today_date_str()

    def get_source(self): # TODO
        """
        Returns source/feeder name
        """
        return 'ocr'
        # l_source = self.id.split('/')[:-2]
        # return os.path.join(*l_source)

    def get_basename(self):  # TODO
        return 'ocr'

    def get_link(self, flask_context=False):
        if flask_context:
            url = url_for('correlation.show_correlation', type=self.type, id=self.id)
        else:
            url = f'{baseurl}/correlation/show?type={self.type}&id={self.id}'
        return url

    def get_svg_icon(self):
        return {'style': 'fas', 'icon': '\uf065', 'color': 'yellow', 'radius': 5}

    def get_image_path(self):
        rel_path = os.path.join(self.id[0:2], self.id[2:4], self.id[4:6], self.id[6:8], self.id[8:10], self.id[10:12], self.id[12:])
        filename = os.path.join(IMAGE_FOLDER, rel_path)
        return os.path.realpath(filename)

    def get_misp_object(self):  # TODO
        obj = MISPObject('instant-message', standalone=True)
        obj_date = self.get_date()
        if obj_date:
            obj.first_seen = obj_date
        else:
            self.logger.warning(
                f'Export error, None seen {self.type}:{self.subtype}:{self.id}, first={obj_date}')

        # obj_attrs = [obj.add_attribute('first-seen', value=obj_date),
        #              obj.add_attribute('raw-data', value=self.id, data=self.get_raw_content()),
        #              obj.add_attribute('sensor', value=get_ail_uuid())]
        obj_attrs = []
        for obj_attr in obj_attrs:
            for tag in self.get_tags():
                obj_attr.add_tag(tag)
        return obj

    # options: set of optional meta fields
    def get_meta(self, options=None, timestamp=None, translation_target=''):
        """
        :type options: set
        :type timestamp: float
        """
        if options is None:
            options = set()
        meta = self.get_default_meta(tags=True)
        meta['content'] = self.get_content()

        # optional meta fields
        if 'investigations' in options:
            meta['investigations'] = self.get_investigations()
        if 'link' in options:
            meta['link'] = self.get_link(flask_context=True)
        if 'icon' in options:
            meta['icon'] = self.get_svg_icon()
        if 'img' in options:
            meta['img'] = self.draw_bounding_boxs()
        if 'map' in options:
            meta['map'] = self.get_img_map_coords()

        # # TODO
        # if 'language' in options:
        #     meta['language'] = self.get_language()
        # if 'translation' in options and translation_target:
        #     if meta.get('language'):
        #         source = meta['language']
        #     else:
        #         source = None
        #     meta['translation'] = self.translate(content=meta.get('content'), source=source, target=translation_target)
        #     if 'language' in options:
        #         meta['language'] = self.get_language()
        return meta

    def get_objs_container(self):
        objs_containers = set()
        # chat
        objs_containers.add(self.get_first_correlation('chat'))
        subchannel = self.get_first_correlation('chat-subchannel')
        if subchannel:
            objs_containers.add(subchannel)
        thread = self.get_first_correlation('chat-thread')
        if thread:
            objs_containers.add(thread)
        return objs_containers

    def create_coord_str(self, bbox):
        c1, c2, c3, c4 = bbox
        x1, y1 = c1
        x2, y2 = c2
        x3, y3 = c3
        x4, y4 = c4
        return f'{int(x1)},{int(y1)}:{int(x2)},{int(y2)}:{int(x3)},{int(y3)}:{int(x4)},{int(y4)}'

    def _unpack_coord(self, coord):
        return coord.split(',', 1)

    def get_coords(self):
        coords = []
        for extracted in r_object.smembers(f'ocr:{self.id}'):
            coord = []
            bbox = extracted.split(':', 4)[:-1]
            for c in bbox:
                x, y = self._unpack_coord(c)
                coord.append((int(x), int(y)))
            coords.append(coord)
        return coords

    def get_img_map_coords(self):
        coords = []
        for extracted in r_object.smembers(f'ocr:{self.id}'):
            extract = extracted.split(':', 4)
            x1, y1 = self._unpack_coord(extract[0])
            x2, y2 = self._unpack_coord(extract[1])
            x3, y3 = self._unpack_coord(extract[2])
            x4, y4 = self._unpack_coord(extract[3])
            coords.append((f'{x1},{y1},{x2},{y2},{x3},{y3},{x4},{y4}', extract[4]))
        return coords

    def edit(self, coordinates, text, new_text, new_coordinates=None):
        pass

    def add(self, coordinates, text):
        val = f'{coordinates}:{text}'
        return r_object.sadd(f'ocr:{self.id}', val)

    def remove(self, val):
        return r_object.srem(f'ocr:{self.id}', val)

    def create(self, extracted_texts, tags=[]):
        r_object.sadd(f'{self.type}:all', self.id)
        for extracted in extracted_texts:
            bbox, text = extracted
            if len(text) > 1:
                str_coords = self.create_coord_str(bbox)
                self.add(str_coords, text)
                self.add_correlation('image', '', self.id)

        for tag in tags:
            self.add_tag(tag)

    # # WARNING: UNCLEAN DELETE /!\ TEST ONLY /!\
    def delete(self):
        r_object.delete(f'ocr:{self.id}')

    def draw_bounding_boxs(self):
        img = Image.open(self.get_image_path()).convert("RGBA")
        draw = ImageDraw.Draw(img)
        for bbox in self.get_coords():
            c1, c2, c3, c4 = bbox
            draw.line((tuple(c1), tuple(c2)), fill="yellow", width=2)
            draw.line((tuple(c2), tuple(c3)), fill="yellow", width=2)
            draw.line((tuple(c3), tuple(c4)), fill="yellow", width=2)
            draw.line((tuple(c4), tuple(c1)), fill="yellow", width=2)
        # img.show()
        buff = BytesIO()
        img.save(buff, "PNG")
        return buff.getvalue()


def create(obj_id, detections, tags=[]):
    obj = Ocr(obj_id)
    if not obj.exists():
        obj.create(detections, tags=tags)
    # TODO Edit
    return obj

# TODO preload languages
def extract_text(image_path, languages, threshold=0.2):
    import easyocr
    reader = easyocr.Reader(languages, verbose=False)
    texts = reader.readtext(image_path)
    # print(texts)
    extracted = []
    for bbox, text, score in texts:
        if score > threshold:
            extracted.append((bbox, text))
    return extracted

# TODO OCRS Class

def get_ids():
    return r_object.smembers(f'ocr:all')

def get_all_ocrs_objects(filters={}):
    for obj_id in get_ids():
        yield Ocr(obj_id)

