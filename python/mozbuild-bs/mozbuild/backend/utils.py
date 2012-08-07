# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This file provides common utility functions used by multiple backends.

import os.path


def makefile_output_path(srcdir, objdir, makefile):
    """Obtain the output path for a Makefile.in."""

    assert makefile.filename.endswith('.in')
    assert makefile.filename.startswith(srcdir)

    basename = os.path.basename(makefile.filename).rstrip('.in')
    input_directory = makefile.directory
    leaf = input_directory[len(srcdir) + 1:]

    return os.path.join(objdir, leaf, basename)

def substitute_makefile(makefile, frontend):
    variables = dict(frontend.autoconf)
    variables['top_srcdir'] = frontend.srcdir
    variables['srcdir'] = makefile.directory

    assert makefile.directory.startswith(frontend.srcdir)

    relative = makefile.directory[len(frontend.srcdir)+1:]
    variables['relativesrcdir'] = relative

    levels = relative.count('/') + 1
    paths = ['..' for i in range(0, levels)]

    if levels == 1:
        if not len(relative):
            paths = ['.']

    depth = os.path.join(*paths)
    variables['DEPTH'] = depth

    makefile.perform_substitutions(variables, raise_on_missing=True)
