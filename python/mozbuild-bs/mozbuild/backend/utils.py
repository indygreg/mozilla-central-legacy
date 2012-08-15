# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

# This file provides common utility functions used by multiple backends.

import os


def makefile_output_path(srcdir, objdir, makefile):
    """Obtain the output path for a Makefile.in."""

    assert makefile.filename.endswith('.in')
    assert makefile.filename.startswith(srcdir)
    assert not makefile.filename.startswith(objdir)

    basename = os.path.basename(makefile.filename).rstrip('.in')
    input_directory = os.path.dirname(makefile.filename)
    leaf = input_directory[len(srcdir) + 1:]

    return os.path.join(objdir, leaf, basename)

def substitute_makefile(makefile, frontend):
    assert makefile.directory.startswith(frontend.objdir)
    assert makefile.relative_directory is not None

    variables = dict(frontend.autoconf)
    variables['top_srcdir'] = frontend.srcdir.replace(os.sep, '/')
    variables['srcdir'] = os.path.join(frontend.srcdir,
            makefile.relative_directory).replace(os.sep, '/').rstrip('/')
    variables['relativesrcdir'] = makefile.relative_directory.replace(os.sep,
        '/').rstrip('/')

    depth = os.path.relpath(frontend.objdir,
        makefile.directory).replace(os.sep, '/')
    variables['DEPTH'] = depth

    makefile.perform_substitutions(variables, raise_on_missing=True)
