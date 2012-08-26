# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this
# file, You can obtain one at http://mozilla.org/MPL/2.0/.

# This file contains code for reading metadata from the build system into
# data structures.

import ast
import os

class ASTValidator(ast.NodeVisitor):
    """Validates a Python AST conforms to our rules for a build file.

    Build definition files are Python scripts. However, the subset of Python
    they are allowed to perform is limited. This class is the validator used
    to enforce those limitations.

    The top-most AST node from a parsed file is fed into start(). From there,
    we behave like a typical ast.NodeVisitor. visit() is called for every
    node in the AST. We rely on the default implementation, which calls
    self.visit_<classname> if it exists or self.generic_visit() if it doesn't.
    """
    def __init__(self):
        self.depth = 0


    def start(self, node):
        assert isinstance(node, ast.Module)

        self.walk(node)

        assert self.depth == 0

    def walk(self, node):
        self.visit(node)
        self.depth += 1

        for child in ast.iter_child_nodes(node):
            self.walk(child)

        self.depth -= 1

    def generic_visit(self, node):
        print '%sNode: %s' % (' ' * 2 * self.depth, node)
        #for field in ast.iter_fields(node):
        #    print field

        return node

class BuildReader(object):

    def __init__(self, topsrcdir):
        self.topsrcdir = topsrcdir
        self.validator = ASTValidator()

    def read(self):
        # We start in the root directory and descend according to what we find.
        path = os.path.join(self.topsrcdir, 'build.mb')

        self.read_mozbuild(path)

    def read_mozbuild(self, path):
        source = None

        with open(path, 'rb') as fh:
            source = fh.read()

        node = ast.parse(source, path)
        self.validator.start(node)
