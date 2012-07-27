# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import hashlib

def hash_file(path):
    """Hashes a file specified by the path given and returns the hex digest."""

    h = hashlib.sha1()

    with open(path, 'rb') as fh:
        h.update(fh.read())

    return h.hexdigest()
