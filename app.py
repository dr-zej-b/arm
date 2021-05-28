#!/usr/bin/env python
#
# Copyright 2009 Facebook
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.
"""Simplified chat demo for websockets.

Authentication, error handling, etc are left as an exercise for the reader :)
"""

import logging
import tornado.escape
import tornado.ioloop
import tornado.options
import tornado.web
import tornado.websocket
import os.path
import os
import glob
import json
import time
import maestro
import re

from tornado.options import define, options

define("port", default=9000, help="run on the given port", type=int)

devs = glob.glob("/dev/ttyACM*")
dev_re = re.compile('ACM(\d+)')
dev_num = min([int(dev_re.findall(x)[0]) for x in devs])
arm = maestro.Controller(f'/dev/ttyACM{dev_num}',config_file="config.json")

pwm_vector = {"target_pwm": []}


def update_positions():
    cmd = 'updatePosition'
    try:
        param = {'pwm': arm.get_all_positions()}
        msg = {"cmd": cmd, "param": param}
        logging.info("update_positions, msg = {}".format(msg))
    except:
        param = {'pwm': arm.get_all_positions()}

        msg = {"cmd": cmd, "param": param}
        logging.info("ERROR in: update_positions")
    return msg


class Application(tornado.web.Application):
    def __init__(self):
        handlers = [(r"/", MainHandler), 
        (r"/ws", WebSocketHandler),
        (r"/api/(\w+)/(.*)", ApiHandler),
        ]
        settings = dict(
            cookie_secret="__TODO:_GENERATE_YOUR_OWN_RANDOM_VALUE_HERE__",
            template_path=os.path.join(os.path.dirname(__file__), "templates"),
            static_path=os.path.join(os.path.dirname(__file__), "static"),
            xsrf_cookies=True,
            debug=True,
        )
        super(Application, self).__init__(handlers, **settings)


class MainHandler(tornado.web.RequestHandler):
    def get(self):
        seq_files = glob.glob("*.seq")
        self.render("app.html", seq_files=seq_files)


class ApiHandler(tornado.web.RequestHandler):

    def get(self, *arg):
        
        try:
            cmd_args = json.loads(arg[1])

            if "set_speed" in arg[0]:
                for (chan, val) in enumerate(cmd_args):
                    print("chan:{}, val:{}".format(chan, val))
                    arm.set_speed(chan, val)
                ret_msg = 'done'
        except:
            ret_msg = 'error'
        self.write(ret_msg)

    def put(self, *arg, **kwargs):
        print("put")
        self.write('{"is_active": "false"}')

    def post(self, *arg, **kwargs):
        print("post ----------------------------------------------")
        print(self.request)
        body = self.request.body.decode("utf-8")
        try:
            out = json.loads(body)
            out["dev"] = out["active"]
        except:
            out = 'could not decode'
        print("body = {}, type = {}, json = {}".format(body, type(body), out))

        self.write('{"is_active": "true"}')


class WebSocketHandler(tornado.websocket.WebSocketHandler):
    waiters = set()
    cache = []
    cache_size = 200

    def get_compression_options(self):
        # Non-None enables compression with default options.
        return {}

    def open(self):
        WebSocketHandler.waiters.add(self)
        msg = update_positions()
        WebSocketHandler.send_updates(tornado.escape.json_encode(msg))

    def on_close(self):
        WebSocketHandler.waiters.remove(self)

    @classmethod
    def update_cache(cls, chat):
        cls.cache.append(chat)
        if len(cls.cache) > cls.cache_size:
            cls.cache = cls.cache[-cls.cache_size:]

    @classmethod
    def send_updates(cls, chat):
        logging.info("sending message to %d waiters", len(cls.waiters))
        for waiter in cls.waiters:
            try:
                waiter.write_message(chat)
            except:
                logging.error("Error sending message", exc_info=True)

    def on_message(self, message):
        logging.info("got message %r", message)

        if "button" in message:
            parsed = tornado.escape.json_decode(message)

            if "SaveFile" in parsed['cmd']:
                filename = parsed['filename']
                filename, file_extension = os.path.splitext(filename)
                if ".seq" not in file_extension:
                    filename = filename + ".seq"

                logging.info("Saving to file: {}".format(filename))
                fid = open(filename, 'w')
                fid.write(json.dumps(parsed))
                fid.close()

            if "Update" in parsed['cmd']:
                l = parsed['body']['target_pwm']
                l.append(arm.config['last_position'][5])
                arm.set_target_vector(l)

            if "Run" in parsed['cmd']:
                logging.debug("Running Sequence: run {} times".format(parsed['number_of_times']))
                for ii in range(parsed['number_of_times']):
                    for frame in parsed['body']:
                        time.sleep(frame['sleep_before'])
                        for chan in range(5):
                            arm.set_speed(chan, frame['speed'])

                        if len(frame['target_pwm']) == 5:
                            frame['target_pwm'].append(1500)

                        arm.set_target_vector(frame['target_pwm'], match_speed=frame['match_speed'], wait=True)
                        msg = update_positions()
                        WebSocketHandler.send_updates(tornado.escape.json_encode(msg))
                        time.sleep(frame['sleep'])

            if "Delete Sequence" in parsed['cmd']:
                filename = parsed['param']
                if os.path.exists(filename):
                    os.remove(filename)

            if "Home" in parsed['cmd']:
                arm.go_home()
                msg = update_positions()
                WebSocketHandler.send_updates(tornado.escape.json_encode(msg))

            if "Loadfile" in parsed['cmd']:
                filename = parsed['filename']
                fid = open(filename, 'r')
                from_file = json.loads(fid.read())
                fid.close()
                logging.info("loaded file {}".format(filename))
                msg = {
                    "cmd": "FromLoadedFile",
                    "param": from_file,
                }
                WebSocketHandler.send_updates(tornado.escape.json_encode(msg))

            if "Set Home" in parsed['cmd']:
                arm.config['home'] = arm.get_all_positions()
                print(arm.config['home'])

        elif "cmd" in message:
            parsed = tornado.escape.json_decode(message)

            chan = int(parsed['id'][1])
            pwm = int(parsed["body"])
            if "L" in parsed['id'][0]:
                logging.info("moving left arm {}".format(int(parsed["body"])))
                arm.set_target(chan, pwm)

            #msg = update_positions()
            #ChatSocketHandler.send_updates(tornado.escape.json_encode(msg))

        else:
            # parsed = tornado.escape.json_decode(message)
            # chat = {"id": str(uuid.uuid4()), "body": parsed["body"]}
            # chat["html"] = tornado.escape.to_basestring(
            #     self.render_string("message.html", message=chat)
            # )

            # ChatSocketHandler.update_cache(chat)
            #ChatSocketHandler.send_updates(chat)
            pass


def main():
    tornado.options.parse_command_line()
    app = Application()
    app.listen(options.port, address='0.0.0.0')
    tornado.ioloop.IOLoop.current().start()


if __name__ == "__main__":
    main()

