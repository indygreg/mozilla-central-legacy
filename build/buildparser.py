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
from os.path import abspath, exists, isabs, join, dirname
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

        path = join(objdir, 'Makefile')
        if not exists(path):
            raise Exception('Makefile does not exist: %s' % path)

        makefile = Makefile(workdir=self.dir)
        makefile.include(path)
        makefile.finishparsing()

        self.topmakefile = BuildMakefile(makefile)

    def get_tiers(self):
        return self.topmakefile._get_variable_split('TIERS')

    def get_platform_dirs(self):
        return self.topmakefile._get_variable_split('tier_platform_dirs')

    def get_base_dirs(self):
        '''Obtain a list of the configured base directories'''
        return self.topmakefile._get_variable_split('tier_base_dirs')

    def get_dir_makefile(self, path):
        full = join(self.dir, path)
        file = join(full, 'Makefile')

        if not exists(file):
            raise Exception('path does not exist: %s' % file)

        m = Makefile(workdir=full)
        m.include(file)
        m.finishparsing()

        return (BuildMakefile(m), full, file)

    def get_top_source_directory(self):
        return self.topmakefile._get_variable_string('topsrcdir')

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

    def build_visual_studio_files(self, python=None, version='2008', pymake=None):
        '''Build Visual Studio files for the tree

        Calling this will result in a bunch of files being written to
        objdir/msvc.

        Currently, the written files are far from feature complete. For
        example, we don't yet know how to handle all the Makefiles in the
        tree.

        Arguments:

          version - Visual Studio product version to write files for. One of
                    {2005, 2008, 2010, or 2011}. Specified as a string.

          pymake - Path to pymake command line program. Defaults to
                   topsrcdir/pymake/make.py.
          python - Path to python executable that is runnable from Visual
                   Studio. Currently, this must be specified. In the future, we
                   might auto-discover it.
        '''
        if pymake is None:
            pymake = join(self.get_top_source_directory(), 'build', 'pymake', 'make.py')

        if python is None:
            # TODO try to find by environment
            raise Exception('Could not find Python')

        builder = VisualStudioBuilder()
        outdir = join(self.dir, 'msvc')

        if not exists(outdir):
            mkdir(outdir)

        # TODO fix directories causing us hurt
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

        def handle_project(project, id, name):
            filename = '%s.vcproj' % name
            projfile = join(outdir, filename)

            with open(projfile, 'w') as fh:
                #print 'Writing %s' % projfile
                fh.write(proj)

            entry = {
                'id':       id,
                'name':     name,
                'filename': filename,
            }

            projects[id] = entry

        for dir in process_dirs:
            if dir in ignore_dirs:
                continue

            print 'Processing directory: %s' % dir
            m = self.get_dir_makefile(dir)[0]

            if m.is_module():
                module = m.get_module()

                #print '%s Processing module in: %s' % ( getpid(), dir )

                info = self.get_module_data(dir)
                for library in info['libraries']:
                    proj, id, name = builder.build_project_for_library(
                        library, module, version=version
                    )

                    handle_project(proj, id, name)
            else:
                # fall back to generic case
                print 'UNRECOGNIZED MAKEFILE PATTERN: %s' % dir
                proj, id, name = builder.build_project_for_generic(
                    m, version=version
                )
                handle_project(proj, id, name)


        # now produce the Solution file
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

        # solution properties file defines a bunch of constants
        props = Element('VisualStudioPropertySheet', ProjectType='Visual C++',
            Version='8.00',
            Name='mozilla-build',
        )
        props.append(Element('UserMacro', Name='PYTHON', Value=python))
        props.append(Element('UserMacro', Name='PYMAKE', Value='$(PYTHON) %s' % pymake))
        propspath = join(outdir, 'mozilla.vsprops')
        with open(propspath, 'w') as fh:
            fh.write(xml.etree.ElementTree.tostring(props, encoding='utf-8'))

class BuildMakefile(object):
    '''A wrapper around a PyMake Makefile tailored to Mozilla's build system'''

    def __init__(self, makefile):
        '''Construct from an existing PyMake Makefile instance'''
        self.makefile = makefile
        self.filename = makefile.included[0][0]
        self.dir      = dirname(self.filename)

        self.module = self.get_module()

        objtop = abspath(join(self.dir, self._get_variable_string('DEPTH')))
        absdir = abspath(self.dir)

        self.reldir = absdir[len(objtop)+1:]

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

    def get_source_dir(self):
        return self._get_variable_string('srcdir')

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

        return self.build_project(
            version=version,
            name='%s_%s' % ( module, library['name'] ),
            dir=library['dir'],
            source_dir=library['srcdir'],
            cpp_sources=library['cppsrcs'],
            export_headers=library['exports'],
            internal_headers=library['mozillaexports'],
            idl_sources=library['xpidlsrcs']
        )

    def build_project_for_generic(self, makefile, version='2008'):
        '''Takes a BuildMakefile and produces a project file

        This version is called when we don't know how to process the Makefile.
        It simply calls out to PyMake.
        '''
        return self.build_project(
            version=version,
            name=makefile.reldir.replace('\\', '_').replace('/', '_'),
            dir=makefile.dir,
            source_dir=makefile.get_source_dir()
        )

    def build_project(self, version='2008', name=None, dir=None,
                      source_dir=None,
                      cpp_sources=[], export_headers=[], internal_headers=[],
                      idl_sources=[]
                      ):
        '''Convert parameters into a Visual Studio Project File string.

        Arguments:

          version  string
                   Visual Studio Product Version. One of {2005, 2008, 2010,
                    2011}.

          name  string
                Project Name

          dir  string
               Directory in tree this project corresponds to

          source_dir  string
                      Directory where source files can be found

          cpp_sources  list
                       C++ source files for this project

          export_headers  list
                          header files exported as part of library

          internal_headers list
                           header files used internally

          idl_sources  list
                       IDL source files
        '''

        if not name:
            raise Exception('name must be specified')

        if not dir:
            raise Exception('dir must be specified')

        if not source_dir:
            raise Exception('source_dir must be specified')

        id = str(uuid1())
        strversion = visual_studio_product_to_internal_version(version)

        root = Element('VisualStudioProject', attrib={
            'ProjectType':   'Visual C++',
            'Version':       strversion,
            'Name':          name,
            'ProjectGUID':   id,
            'RootNamespace': 'mozilla',
            'Keyword':       'Win32Proj',
        })

        platforms = Element('Platforms')
        platforms.append(Element('Platform', Name='Win32'))
        root.append(platforms)
        root.append(Element('ToolFiles'))

        configuration_type = '0' # Makefile

        configurations = Element('Configurations')
        configuration = Element('Configuration',
            Name='Build|Win32',
            ConfigurationType=configuration_type,
            CharacterSet='1',
            InheritedPropertySheets='.\mozilla.vsprops'
        )

        pymake = '$(PYMAKE) -C %s' % dir

        tool_make = Element('Tool', Name='VCNMakeTool',
            BuildCommandLine=pymake,
            # TODO RebuildCommandLine
            CleanCommandLine='%s clean' % pymake,
            PreprocessorDefinitions='',
            IncludeSearchPath='',
            AssemblySearchPath='',
            # TODO Output
        )
        configuration.append(tool_make)

        configurations.append(configuration)
        root.append(configurations)

        files = Element('Files')
        if len(cpp_sources):
            filter_source = Element('Filter',
                Name='Source Files',
                Filter='cpp;c;cc;cxx',
                UniqueIdentifier=str(uuid1())
            )
            for f in cpp_sources:
                filter_source.append(Element('File', RelativePath=join(source_dir, f)))
            files.append(filter_source)

        all_headers = export_headers
        all_headers.extend(internal_headers)
        all_headers.sort()
        if len(all_headers):
            filter_headers = Element('Filter',
                Name='Header Files',
                Filter='h;hpp;hxx',
                UniqueIdentifier=str(uuid1())
            )
            for f in all_headers:
                filter_headers.append(Element('File', RelativePath=join(source_dir, f)))
            files.append(filter_headers)

        idl_sources.sort()
        if len(idl_sources):
            filter_idl = Element('Filter',
                Name='IDL Files',
                Filter='idl',
                UniqueIdentifier=str(uuid1())
            )
            for f in idl_sources:
                filter_idl.append(Element('File', RelativePath=join(source_dir, f)))
            files.append(filter_idl)

        root.append(files)

        root.append(Element('Globals'))

        s = xml.etree.ElementTree.tostring(root, encoding='utf-8')
        return (s, id, name)