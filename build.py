#!/usr/bin/python
# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import sys

# TODO these should magically come from the environment.
# [gps] I want a virtualenv environment for the source tree!
sys.path.append('build')
sys.path.append('build/pymake')
sys.path.append('other-licenses/ply')
sys.path.append('xpcom/idl-parser')

import buildsplendid.cli
import os.path

# All of the code is in a module because EVERYTHING IS A LIBRARY.
b = buildsplendid.cli.BuildTool(os.path.dirname(os.path.abspath(__file__)))
b.run(sys.argv[1:])
