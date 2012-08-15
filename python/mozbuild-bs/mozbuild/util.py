# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This file contains miscellaneous utility functions that don't belong anywhere
# in particular.

import hashlib
import os

from StringIO import StringIO


def hash_file(path):
    """Hashes a file specified by the path given and returns the hex digest."""

    # If the hashing function changes, this may invalidate lots of cached data.
    # Don't change it lightly.
    h = hashlib.sha1()

    with open(path, 'rb') as fh:
        while True:
            data = fh.read(8192)

            if not len(data):
                break

            h.update(data)

    return h.hexdigest()


class FileAvoidWrite(StringIO):
    """file-like object that buffers its output and only writes it to disk
    if the new contents are different from what the file may already contain.

    This was shamelessly stolen from ConfigStatus.py.
    """
    def __init__(self, filename):
        self.filename = filename
        StringIO.__init__(self)

    def close(self):
        buf = self.getvalue()
        StringIO.close(self)

        try:
            fh = open(self.filename, 'rU')
        except IOError:
            pass
        else:
            try:
                if fh.read() == buf:
                    return
            except IOError:
                pass
            finally:
                fh.close()

        parent_directory = os.path.dirname(self.filename)
        if not os.path.exists(parent_directory):
            os.makedirs(parent_directory)

        with open(self.filename, 'w') as fh:
            fh.write(buf)

    def __enter__(self):
        return self

    def __exit__(self, type, value, traceback):
        self.close()
