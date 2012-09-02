# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import unittest

from mozbuild.frontend.reader import GlobalNamespace
from mozbuild.frontend.reader import LocalNamespace
from mozbuild.frontend.variables import FRONTEND_VARIABLES

class TestGlobalNamespace(unittest.TestCase):
    def test_builtins(self):
        ns = GlobalNamespace()

        self.assertIn('__builtins__', ns)
        self.assertEqual(ns['__builtins__']['True'], True)

    def test_key_rejection(self):
        # Lowercase keys should be rejected during normal operation.
        ns = GlobalNamespace()

        with self.assertRaises(KeyError):
            ns['foo'] = True

        # Unknown uppercase keys should be rejected.
        with self.assertRaises(KeyError):
            ns['FOO'] = True

        # Non-string keys should be rejected
        with self.assertRaises(TypeError):
            value = ns[1]

    def test_allowed_set(self):
        self.assertIn('DIRS', FRONTEND_VARIABLES)

        ns = GlobalNamespace()

        ns['DIRS'] = ['foo']
        self.assertEqual(ns['DIRS'], ['foo'])

    def test_allow_all_writes(self):
        ns = GlobalNamespace()

        with ns as d:
            d['foo'] = True
            self.assertTrue(d['foo'])

        with self.assertRaises(KeyError):
            ns['foo'] = False

        self.assertTrue(d['foo'])

class TestLocalNamespace(unittest.TestCase):
    def test_global_proxy_reads(self):
        g = GlobalNamespace()
        g['DIRS'] = ['foo']

        l = LocalNamespace(g)

        self.assertEqual(l['DIRS'], g['DIRS'])

    def test_global_proxy_writes(self):
        g = GlobalNamespace()
        l = LocalNamespace(g)

        l['DIRS'] = ['foo']

        self.assertEqual(l['DIRS'], ['foo'])
        self.assertEqual(g['DIRS'], ['foo'])
