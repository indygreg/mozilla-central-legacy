#!/usr/bin/env python
# Copyright (c) 2012 The WebRTC project authors. All Rights Reserved.
#
# Use of this source code is governed by a BSD-style license
# that can be found in the LICENSE file in the root of the source
# tree. An additional intellectual property rights grant can be found
# in the file PATENTS.  All contributing project authors may
# be found in the AUTHORS file in the root of the source tree.

import sys

supplement_gypi = """#!/usr/bin/env python
# This file is generated by %s.  Not for check-in.
# Please see the WebRTC DEPS file for details.
{
  'variables': {
    'build_with_chromium': 0,
    'inside_chromium_build': 0,
  }
}
"""

def main(argv):
  open(argv[1], 'w').write(supplement_gypi % argv[0])

if __name__ == '__main__':
  sys.exit(main(sys.argv))
