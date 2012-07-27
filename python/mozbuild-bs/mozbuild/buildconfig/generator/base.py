# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

from mozbuild.base import Base

class Generator(Base):
    def __init__(self, frontend):
        Base.__init__(self, frontend.config)

        self.frontend = frontend

    def generate(self):
        raise Exception('generate() must be implemented in %s' % __name__)

    def clean(self):
        raise Exception('clean() must be implemented in %s' % __name__)
