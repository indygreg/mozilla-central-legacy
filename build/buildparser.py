# ***** BEGIN LICENSE BLOCK *****
# Version: MPL 1.1/GPL 2.0/LGPL 2.1
#
# The contents of this file are subject to the Mozilla Public License Version
# 1.1 (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
# http://www.mozilla.org/MPL/
#
# Software distributed under the License is distributed on an "AS IS" basis,
# WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
# for the specific language governing rights and limitations under the
# License.
#
# The Original Code is Mozilla build system.
#
# The Initial Developer of the Original Code is
# Mozilla Foundation.
# Portions created by the Initial Developer are Copyright (C) 2011
# the Initial Developer. All Rights Reserved.
#
# Contributor(s):
#  Gregory Szorc <gps@mozilla.com>
#
# Alternatively, the contents of this file may be used under the terms of
# either the GNU General Public License Version 2 or later (the "GPL"), or
# the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
# in which case the provisions of the GPL or the LGPL are applicable instead
# of those above. If you wish to allow use of your version of this file only
# under the terms of either the GPL or the LGPL, and not to allow others to
# use your version of this file under the terms of the MPL, indicate your
# decision by deleting the provisiwons above and replace them with the notice
# and other provisions required by the GPL or the LGPL. If you do not delete
# the provisions above, a recipient may use your version of this file under
# the terms of any one of the MPL, the GPL or the LGPL.
#
# ***** END LICENSE BLOCK *****

# This file contains modules for extracting useful details from the Makefiles
# in the tree. Parts are very hacky and there are many bugs.
#
# Currently, the Visual Studio integration just creates projects with files.
# Building doesn't work at all.

from os import getpid, mkdir
from os.path import exists, isabs, join, dirname
from pymake.data import Makefile
from shutil import rmtree
from uuid import uuid1
from xml.etree.ElementTree import ElementTree, Element

import xml.etree.ElementTree

# TODO validate mappings are correct. only 2008 confirmed so far
def visual_studio_product_to_internal_version(version, solution=False):
    if solution:
        if version == '2005':
            return '9.00'
        elif version == '2008':
            return '10.00'
        elif version == '2010':
            return '11.00'
        elif version == '2011':
            return '12.00'
        else:
            raise Exception('Unknown version seen: %s' % version)
    else:
        if version == '2005':
            return '8.00'
        elif version == '2008':
            return '9.00'
        elif version == '2010':
            return '10.00'
        elif version == '2011':
            return '11.00'
        else:
            raise Exception('Unknown version seen: %s' % version)

class BuildParser(object):
    '''Extracts metadata from the build system.'''

    def __init__(self, objdir):
        if not isabs(objdir):
            raise Exception('Path not absolute: %s' % objdir)

        self.dir = objdir
        self.topmakefile = Makefile(workdir=self.dir)

        path = join(objdir, 'Makefile')
        if not exists(path):
            raise Exception('Makefile does not exist: %s' % path)

        self.topmakefile.include(path)
        self.topmakefile.finishparsing()

    def _get_variable_as_list(self, v):
        value = self.topmakefile.variables.get(v, True)[2]
        return value.resolvesplit(self.topmakefile, self.topmakefile.variables)

    def get_tiers(self):
        return self._get_variable_as_list('TIERS')

    def get_platform_dirs(self):
        return self._get_variable_as_list('tier_platform_dirs')

    def get_base_dirs(self):
        '''Obtain a list of the configured base directories'''
        return self._get_variable_as_list('tier_base_dirs')

    def get_dir_makefile(self, path):
        full = join(self.dir, path)
        file = join(full, 'Makefile')

        if not exists(file):
            raise Exception('path does not exist: %s' % file)

        m = Makefile(workdir=full)
        m.include(file)
        m.finishparsing()

        return (BuildMakefile(m), full, file)

    def get_module_data(self, path):
        makefile, full, file = self.get_dir_makefile(path)
        assert(makefile.is_module())

        d = {
            'libraries': []
        }

        dirs = makefile.get_dirs()
        dirs.sort()
        for dir in dirs:
            subpath = join(path, dir)
            submake, subfull, subfile = self.get_dir_makefile(subpath)

            library = submake.get_library()
            if library is not None:
                d['libraries'].append(submake.get_library_info())
                continue

            print 'UNHANDLED DIRECTORY: %s' % subpath

        return d

    def build_visual_studio_files(self, version='2008'):
        builder = VisualStudioBuilder()
        outdir = join(self.dir, 'msvc')

        if not exists(outdir):
            mkdir(outdir)

        # TODO fix directories causing us hurt for unknown reasons
        ignore_dirs = [
            'js/src/xpconnect', # hangs
            'modules/libbz2',   # somehow forks and calls itself recursively
            'security/manager', # hangs
        ]

        projects = {}
        strversion = visual_studio_product_to_internal_version(version, True)

        process_dirs = self.get_platform_dirs()
        process_dirs.extend(self.get_base_dirs())
        process_dirs.sort()
        for dir in process_dirs:
            if dir in ignore_dirs:
                continue

            print 'Processing directory: %s' % dir
            m = self.get_dir_makefile(dir)[0]

            if not m.is_module():
                print 'UNHANDLED DIRECTORY: %s' % dir
                continue

            module = m.get_module()

            #print '%s Processing module in: %s' % ( getpid(), dir )

            info = self.get_module_data(dir)
            for library in info['libraries']:
                proj, id = builder.build_project_for_library(library, module,
                                                             version=version)

                name = '%s_%s' % ( module, library['name'])
                filename = '%s.vcproj' % name
                projfile = join(outdir, filename)

                with open(projfile, 'w') as fh:
                    #print 'Writing %s' % projfile
                    fh.write(proj)

                entry = {
                    'id':       id,
                    'name':     name,
                    'module':   module,
                    'library':  library,
                    'filename': filename,
                }

                projects[id] = entry

        # now product the Solution file
        slnpath = join(outdir, 'mozilla.sln')
        configid = str(uuid1())
        with open(slnpath, 'w') as fh:
            # Visual Studio seems to require this header
            print >>fh, 'Microsoft Visual Studio Solution File, Format Version %s' % strversion

            # write out entries for each project
            for project in projects.itervalues():
                print >>fh, 'Project("{%s}") = "%s", "%s", "{%s}"' % (
                    project['id'], project['name'], project['filename'], configid
                )
                print >>fh, 'EndProject'

            # the global section defines configurations
            print >>fh, 'Global'
            print >>fh, '\tGlobalSection(SolutionConfigurationPlatforms) = preSolution'
            print >>fh, '\t\tBuild|Win32 = Build|Win32'
            print >>fh, '\tEndGlobalSection'
            print >>fh, '\tGlobalSection(ProjectConfiguration) = postSolution'
            for project in projects.itervalues():
                print >>fh, '\t\t{%s}.Build.ActiveCfg = Build|Win32' % project['id']
                print >>fh, '\t\t{%s}.Build.Build.0 = Build|Win32' % project['id']
            print >>fh, '\tEndGlobalSection'
            print >>fh, 'EndGlobal'

class BuildMakefile(object):
    '''A wrapper around a PyMake Makefile tailored to Mozilla's build system'''

    def __init__(self, makefile):
        '''Construct from an existing PyMake Makefile instance'''
        self.makefile = makefile
        self.filename = makefile.included[0][0]
        self.dir      = dirname(self.filename)

        self.module = self.get_module()

    def _get_variable_string(self, name):
        v = self.makefile.variables.get(name, True)[2]
        if v is None:
            return None

        return v.resolvestr(self.makefile, self.makefile.variables)

    def _get_variable_split(self, name):
        v = self.makefile.variables.get(name, True)[2]
        if v is None:
            return []

        return v.resolvesplit(self.makefile, self.makefile.variables)

    def _has_variable(self, name):
        v = self.makefile.variables.get(name, True)[2]
        return v is not None

    def get_dirs(self):
        dirs = self._get_variable_split('DIRS')
        dirs.extend(self._get_variable_split('PARALLEL_DIRS'))

        return dirs

    def is_module(self):
        return self._has_variable('MODULE')

    def get_module(self):
        return self._get_variable_string('MODULE')

    def get_library(self):
        return self._get_variable_string('LIBRARY')

    def is_xpidl_module(self):
        return self._has_variable('XPIDL_MODULE')

    def get_cpp_sources(self):
        return self._get_variable_split('CPPSRCS')

    def get_c_sources(self):
        return self._get_variable_split('CSRCS')

    def get_top_source_dir(self):
        return self._get_variable_string('topsrcdir')

    def get_exports(self):
        return self._get_variable_split('EXPORTS')

    def get_defines(self):
        return self._get_variable_string('DEFINES')

    def get_library_info(self):
        library = self.get_library()
        assert(library is not None)

        d = {
            'name':           library,
            'dir':            self.dir,
            'defines':        self.get_defines(),
            'cppsrcs':        self.get_cpp_sources(),
            'xpidlsrcs':      self._get_variable_split('XPIDLSRCS'),
            'exports':        self._get_variable_split('EXPORTS'),
            'mozillaexports': self._get_variable_split('EXPORTS_mozilla'),
            'srcdir':         self._get_variable_string('srcdir'),
        }

        return d

class VisualStudioBuilder(object):
    def __init__(self):
        pass

    def build_project_for_library(self, library, module, version='2008'):
        '''Takes a library info dict and converts to a project file'''

        id = str(uuid1())
        strversion = visual_studio_product_to_internal_version(version)

        root = Element('VisualStudioProject', attrib={
            'ProjectType':   'Visual C++',
            'Version':       strversion,
            'Name':          '%s_%s' % ( module, library['name'] ),
            'ProjectGUID':   id,
            'RootNamespace': 'mozilla',
            'Keyword':       'Win32Proj',
        })

        platforms = Element('Platforms')
        platforms.append(Element('Platform', Name='Win32'))
        root.append(platforms)
        root.append(Element('ToolFiles'))

        configuration_type = '4' # static library

        configurations = Element('Configurations')
        configuration = Element('Configuration',
            Name='Build|Win32',
            OutputDirectory=library['dir'],
            IntermediateDirectory=library['dir'],
            ConfigurationType=configuration_type,
            CharacterSet='1'
        )

        configurations.append(configuration)
        root.append(configurations)

        files = Element('Files')
        filter_source = Element('Filter',
            Name='Source Files',
            Filter='cpp;c;cc;cxx',
            UniqueIdentifier=str(uuid1())
        )
        for f in library['cppsrcs']:
            filter_source.append(Element('File', RelativePath=join(library['srcdir'], f)))
        files.append(filter_source)

        if len(library['xpidlsrcs']):
            filter_idl = Element('Filter',
                Name='IDL Files',
                Filter='idl',
                UniqueIdentifier=str(uuid1())
            )
            for f in library['xpidlsrcs']:
                filter_idl.append(Element('File', RelativePath=join(library['srcdir'], f)))
            files.append(filter_idl)

        filter_headers = Element('Filter',
            Name='Header Files',
            Filter='h;hpp;hxx',
            UniqueIdentifier=str(uuid1())
        )
        for f in library['exports']:
            filter_headers.append(Element('File', RelativePath=join(library['srcdir'], f)))
        for f in library['mozillaexports']:
            filter_headers.append(Element('File', RelativePath=join(library['srcdir'], f)))
        files.append(filter_headers)

        root.append(files)

        root.append(Element('Globals'))

        s = xml.etree.ElementTree.tostring(root, encoding='utf-8')
        return (s, id)