# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import unittest

from tempfile import NamedTemporaryFile

from mozbuild.config import ConfigProvider
from mozbuild.config import ConfigSettings


CONFIG1 = r"""
[foo]

bar = bar_value
baz = /baz/foo.c
"""

CONFIG2 = r"""
[foo]

bar = value2
"""

class Provider1(ConfigProvider):
    @classmethod
    def _register_settings(cls):
        cls.register_setting('foo', 'bar', ConfigProvider.TYPE_STRING)
        cls.register_setting('foo', 'baz', ConfigProvider.TYPE_ABSOLUTE_PATH)

Provider1.register_settings()

class ProviderDuplicate(ConfigProvider):
    @classmethod
    def _register_settings(cls):
        cls.register_setting('dupesect', 'foo', ConfigProvider.TYPE_STRING)
        cls.register_setting('dupesect', 'foo', ConfigProvider.TYPE_STRING)

class TestConfigProvider(unittest.TestCase):
    def test_construct(self):
        s = Provider1.config_settings

        self.assertEqual(len(s), 1)
        self.assertIn('foo', s)

        self.assertEqual(len(s['foo']), 2)
        self.assertIn('bar', s['foo'])
        self.assertIn('baz', s['foo'])

    def test_duplicate_option(self):
        with self.assertRaises(Exception):
            ProviderDuplicate.register_settings()


class Provider2(ConfigProvider):
    @classmethod
    def _register_settings(cls):
        cls.register_setting('a', 'string', ConfigProvider.TYPE_STRING)
        cls.register_setting('a', 'boolean', ConfigProvider.TYPE_BOOLEAN)
        cls.register_setting('a', 'pos_int',
            ConfigProvider.TYPE_POSITIVE_INTEGER)
        cls.register_setting('a', 'int', ConfigProvider.TYPE_INTEGER)
        cls.register_setting('a', 'abs_path',
            ConfigProvider.TYPE_ABSOLUTE_PATH)
        cls.register_setting('a', 'rel_path',
            ConfigProvider.TYPE_RELATIVE_PATH)
        cls.register_setting('a', 'path', ConfigProvider.TYPE_PATH)

Provider2.register_settings()

class TestConfigSettings(unittest.TestCase):
    def test_empty(self):
        s = ConfigSettings()

        self.assertEqual(len(s), 0)
        self.assertNotIn('foo', s)

    def test_simple(self):
        s = ConfigSettings()
        s.register_provider(Provider1)

        self.assertEqual(len(s), 1)
        self.assertIn('foo', s)

        foo = s['foo']
        foo = s.foo

        self.assertEqual(len(foo), 2)

        self.assertIn('bar', foo)
        self.assertIn('baz', foo)

        foo['bar'] = 'value1'
        self.assertEqual(foo['bar'], 'value1')
        self.assertEqual(foo['bar'], 'value1')

    def test_assignment_validation(self):
        s = ConfigSettings()
        s.register_provider(Provider2)

        a = s.a

        # Assigning an undeclared setting raises.
        with self.assertRaises(KeyError):
            a.undefined = True

        with self.assertRaises(KeyError):
            a['undefined'] = True

        # Basic type validation.
        a.string = 'foo'
        a.string = u'foo'

        with self.assertRaises(ValueError):
            a.string = False

        a.boolean = True
        a.boolean = False

        with self.assertRaises(ValueError):
            a.boolean = 'foo'

        a.pos_int = 5
        a.pos_int = 0

        with self.assertRaises(ValueError):
            a.pos_int = -1

        with self.assertRaises(ValueError):
            a.pos_int = 'foo'

        a.int = 5
        a.int = 0
        a.int = -5

        with self.assertRaises(ValueError):
            a.int = 1.24

        with self.assertRaises(ValueError):
            a.int = 'foo'

        a.abs_path = '/home/gps'

        with self.assertRaises(ValueError):
            a.abs_path = 'home/gps'

        a.rel_path = 'home/gps'
        a.rel_path = './foo/bar'
        a.rel_path = 'foo.c'

        with self.assertRaises(ValueError):
            a.rel_path = '/foo/bar'

        a.path = '/home/gps'
        a.path = 'foo.c'
        a.path = 'foo/bar'
        a.path = './foo'

    def test_retrieval_type(self):
        s = ConfigSettings()
        s.register_provider(Provider2)

        a = s.a

        a.string = 'foo'
        a.boolean = True
        a.pos_int = 12
        a.int = -4
        a.abs_path = '/home/gps'
        a.rel_path = 'foo.c'
        a.path = './foo/bar'

        self.assertIsInstance(a.string, basestring)
        self.assertIsInstance(a.boolean, bool)
        self.assertIsInstance(a.pos_int, int)
        self.assertIsInstance(a.int, int)
        self.assertIsInstance(a.abs_path, basestring)
        self.assertIsInstance(a.rel_path, basestring)
        self.assertIsInstance(a.path, basestring)

    def test_file_reading_single(self):
        temp = NamedTemporaryFile()
        temp.write(CONFIG1)
        temp.flush()

        s = ConfigSettings()
        s.register_provider(Provider1)

        s.load_file(temp.name)

        self.assertEqual(s.foo.bar, 'bar_value')

    def test_file_reading_multiple(self):
        """Loading multiple files has proper overwrite behavior."""
        temp1 = NamedTemporaryFile()
        temp1.write(CONFIG1)
        temp1.flush()

        temp2 = NamedTemporaryFile()
        temp2.write(CONFIG2)
        temp2.flush()

        s = ConfigSettings()
        s.register_provider(Provider1)

        s.load_files([temp1.name, temp2.name])

        self.assertEqual(s.foo.bar, 'value2')

    def test_file_reading_missing(self):
        """Missing files should silently be ignored."""

        s = ConfigSettings()

        s.load_file('/tmp/foo.ini')

    def test_file_writing(self):
        s = ConfigSettings()
        s.register_provider(Provider2)

        s.a.string = 'foo'
        s.a.boolean = False

        temp = NamedTemporaryFile()
        s.write(temp)
        temp.flush()

        s2 = ConfigSettings()
        s2.register_provider(Provider2)

        s2.load_file(temp.name)

        self.assertEqual(s.a.string, s2.a.string)
        self.assertEqual(s.a.boolean, s2.a.boolean)

    def test_write_pot(self):
        s = ConfigSettings()
        s.register_provider(Provider1)
        s.register_provider(Provider2)

        # Just a basic sanity test.
        temp = NamedTemporaryFile()
        s.write_pot(temp)
        temp.flush()
