# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

# This is a sample script showing how to consume the build.mozbuild
# files. Run it with the virtualenv-configured python binary from your
# objdir and it should just work.
#
# e.g. ./objdir/_virtualenv/bin/python buildread.py

import logging
import sys

import mozconfig

from mozbuild.frontend.reader import BuildReader

logging.basicConfig(stream=sys.stderr, level=logging.DEBUG)

reader = BuildReader(mozconfig)
for sandbox in reader.read_topsrcdir():
    pass
