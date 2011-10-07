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

import re
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
        self.topsourcedir = self.topmakefile.get_top_source_dir()

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
            'libraries': [],
            'unhandled': [],
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

            d['unhandled'].append(subpath)

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

        # maps files to be copied in the top project, which always gets built
        top_copy = {
            '$(MOZ_OBJ_DIR)\\mozilla-config.h': '$(MOZ_OBJ_DIR)\\dist\\include\\mozilla-config.h',
        }

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

            m = self.get_dir_makefile(dir)[0]

            if m.is_module():
                module = m.get_module()

                print 'Processing module "%s" in %s' % ( module, dir )

                info = self.get_module_data(dir)
                names = []
                for library in info['libraries']:
                    proj, id, name = builder.build_project_for_library(
                        library, module, version=version
                    )

                    handle_project(proj, id, name)
                    names.append(name)

                    for idl in library['xpidlsrcs']:
                        source = join('$(MOZ_SOURCE_DIR)', library['reldir'], idl)
                        top_copy[source] = join('$(MOZ_OBJ_DIR)', 'dist', 'idl', idl)

                if len(names):
                    print 'Wrote projects for libraries: %s' % ' '.join(names)

                for path in info['unhandled']:
                    print 'Writing generic project for %s' % path
                    m2 = self.get_dir_makefile(path)[0]

                    proj, id, name = builder.build_project_for_generic(
                        m2, version=version
                    )
                    handle_project(proj, id, name)

            else:
                # fall back to generic case
                print 'Writing generic project for %s' % dir
                proj, id, name = builder.build_project_for_generic(
                    m, version=version
                )
                handle_project(proj, id, name)

        # create parent project that does initialization
        # TODO we could probably do this more intelligently

        proj, id, name = builder.build_project(
            version=version,
            name='top',
            type='utility',
            dir=self.topsourcedir,
            source_dir=self.topsourcedir,
            mkdir=[
                '$(MOZ_OBJ_DIR)\\dist',
                '$(MOZ_OBJ_DIR)\\dist\\idl',
                '$(MOZ_OBJ_DIR)\\dist\\include'
            ],
            pre_copy=top_copy,
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

        props.append(Element('UserMacro', Name='MOZ_SOURCE_DIR', Value=self.topsourcedir.replace('/', '\\')))
        props.append(Element('UserMacro', Name='MOZ_OBJ_DIR', Value=self.dir.replace('/', '\\')))

        # IDL generator
        props.append(Element('UserMacro', Name='IDL_HEADER', Value='$(PYTHON) %s --cachedir=%s' % (
            '$(MOZ_SOURCE_DIR)\\xpcom\\idl-parser\\header.py',
            '$(MOZ_SOURCE_DIR)\\xpcom\\idl-parser'
        )))

        python_paths = [
            '$(MOZ_SOURCE_DIR)\\other-licenses\\ply',
            '$(MOZ_SOURCE_DIR)\\xpcom\\idl-parser',
        ]

        props.append(Element('UserMacro',
            Name='PYTHONPATH',
            Value=';'.join(python_paths),
            PerformEnvironmentSet='true'
        ))

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

        self.objtop = abspath(join(self.dir, self._get_variable_string('DEPTH')))
        absdir = abspath(self.dir)

        self.reldir = absdir[len(self.objtop)+1:]

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

    def get_transformed_reldir(self):
        return self.reldir.replace('\\', '_').replace('/', '_')

    def get_library_info(self):
        library = self.get_library()
        assert(library is not None)

        d = {
            'name':            library,
            'normalized_name': self.get_transformed_reldir(),
            'dir':             self.dir,
            'reldir':          self.reldir,
            'objtop':          self.objtop,
            'defines':         self.get_defines(),
            'cppsrcs':         self.get_cpp_sources(),
            'xpidlsrcs':       self._get_variable_split('XPIDLSRCS'),
            'exports':         self._get_variable_split('EXPORTS'),
            'mozillaexports':  self._get_variable_split('EXPORTS_mozilla'),
            'srcdir':          self._get_variable_string('srcdir'),

            # This should arguably be CXXFLAGS and not the COMPILE_ variant
            # which also pulls a lot of other definitions in. If we wanted to
            # do things properly, we could probably pull in the variables
            # separately and define in a property sheet. But that is more
            # complex. This method is pretty safe. Although, it does produce
            # a lot of redundancy in the individual project files.
            'cxxflags':        self._get_variable_split('COMPILE_CXXFLAGS'),

            'static':          self._get_variable_string('FORCE_STATIC_LIB') == '1',
            'shared':          len(self._get_variable_split('SHARED_LIBRARY_LIBS')) > 0,
        }

        return d

class VisualStudioBuilder(object):
    def __init__(self):
        self.RE_WARNING = re.compile('-W(\d+)')
        self.RE_DEFINE = re.compile('-D(.*)$')
        self.RE_UNDEFINE = re.compile('-U(.*)$')
        self.RE_DISABLE_WARNINGS = re.compile('-wd(.*)$')
        self.RE_WARN_AS_ERROR = re.compile('-we(.*)$')
        self.RE_PROGRAM_DATABASE = re.compile('-Fd(.*)$')
        self.RE_INCLUDE = re.compile('-I(.*)$')

    def build_project_for_library(self, library, module, version='2008'):
        '''Takes a library info dict and converts to a project file'''

        type = 'custom'

        if library['static']:
            type = 'static'

        return self.build_project(
            version=version,
            name=library['normalized_name'],
            type=type,
            dir=library['dir'],
            reldir=library['reldir'],
            source_dir=library['srcdir'],
            cpp_sources=library['cppsrcs'],
            export_headers=library['exports'],
            internal_headers=library['mozillaexports'],
            idl_sources=library['xpidlsrcs'],
            idl_out_dir=join(library['objtop'], 'dist', 'include'),
            idl_includes=[ join(library['objtop'], 'dist', 'idl') ],
            defines=library['defines'],
            cxxflags=library['cxxflags'],
        )

    def build_project_for_generic(self, makefile, version='2008'):
        '''Takes a BuildMakefile and produces a project file

        This version is called when we don't know how to process the Makefile.
        It simply calls out to PyMake.
        '''

        return self.build_project(
            version=version,
            name='%s_DUMMY' % makefile.get_transformed_reldir(),
            dir=makefile.dir,
            source_dir=makefile.get_source_dir(),
            defines=makefile._get_variable_string('DEFINES'),
        )

    def build_project(self, version=None, name=None, dir=None, reldir=None,
                      type='custom',
                      source_dir=None,
                      cpp_sources=[], export_headers=[], internal_headers=[],
                      idl_sources=[], idl_out_dir=None, idl_includes=[],
                      defines='', cxxflags=[],
                      pre_copy={}, mkdir=[]
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

          reldir string
                 Relative path in tree project is for

          type string
               Type of project to produce. Must be one of {custom, static}

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

          idl_out_dir  string
                       Where generated IDL files should be placed

          idl_includes  list
                        List of additional paths in which IDLs look for
                        included files.

          defines  string
                   Preprocessor definitions

          pre_copy  dictionary
                    Set of files to copy before the build starts. Keys are
                    source filenames. Values are destination filenames.

          mkdir  list
                 List of directories to create before build.
        '''

        if not version:
            raise Exception('version must be specified')

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

        configuration_type = None
        use_make = False
        static = False

        if type == 'custom':
            configuration_type = '0'
            use_make = True
        elif type == 'static':
            static = True
            configuration_type = '4'
            assert(reldir)
        elif type == 'utility':
            configuration_type = '10'

        configurations = Element('Configurations')
        configuration = Element('Configuration',
            Name='Build|Win32',
            ConfigurationType=configuration_type,
            CharacterSet='1',
            InheritedPropertySheets='.\mozilla.vsprops',
        )

        if reldir:
            configuration.set('IntermediateDirectory', '$(MOZ_OBJ_DIR)\%s' % reldir)
            #configuration.set('BuildLogFile', '$(MOZ_OBJ_DIR)\%s\buildlog.html' % reldir)

        if static:
            configuration.set('OutputDirectory', '$(MOZ_OBJ_DIR)\dist\lib')

        if use_make:
            pymake = '$(PYMAKE) -C %s' % dir
            tool_make = Element('Tool', Name='VCNMakeTool',
                BuildCommandLine=pymake,
                # TODO RebuildCommandLine
                CleanCommandLine='%s clean' % pymake,
                PreprocessorDefinitions=defines,
                IncludeSearchPath='',
                AssemblySearchPath='',
                # TODO Output
            )
            configuration.append(tool_make)

        pre_build_commands = []

        # assemble compiler options from explicit CXXFLAGS
        tool_compiler = Element('Tool', Name='VCCLCompilerTool')
        defines = []
        undefines = []
        disabled_warnings = []
        warn_as_error = []
        includes = []
        force_includes = []
        additional = []

        i = -1
        while True:
            i += 1

            if i == len(cxxflags):
                break

            flag = cxxflags[i]
            lower = flag.lower()
            if lower == '-tc':
                tool_compiler.set('CompileAs', '1')
                continue
            elif lower == '-tp':
                tool_compiler.set('CompileAs', '2')
                continue
            elif lower == '-gy':
                tool_compiler.set('EnableFunctionLevelLinking', 'true')
                continue
            elif lower == '-o1':
                tool_compiler.set('Optimization', '1')
                continue
            elif lower == '-oy':
                tool_compiler.set('OmitFramePointers', 'true')
                continue
            elif flag == '-MT':
                tool_compiler.set('RuntimeLibrary', '0')
                continue
            elif flag == '-MTd':
                tool_compiler.set('RuntimeLibrary', '1')
                continue
            elif flag == '-MD':
                tool_compiler.set('RuntimeLibrary', '2')
                continue
            elif flag == '-MDd':
                tool_compiler.set('RuntimeLibrary', '3')
                continue
            elif lower == '-nologo':
                tool_compiler.set('SuppressStartupBanner', 'true')
                continue
            elif flag == '-Zi':
                tool_compiler.set('DebugInformationFormat', '3')
                continue
            elif flag == '-ZI':
                tool_compiler.set('DebugInformationFormat', '4')
                continue
            elif flag == '-FI':
                assert(i < len(cxxflags))
                force_includes.append(cxxflags[i+1])
                i += 1
                continue

            match = self.RE_INCLUDE.match(flag)
            if match:
                includes.append(match.group(1))
                continue

            match = self.RE_WARNING.match(flag)
            if match:
                tool_compiler.set('WarningLevel', match.group(1))
                continue

            match = self.RE_DEFINE.match(flag)
            if match:
                defines.append(match.group(1))
                continue

            match = self.RE_UNDEFINE.match(flag)
            if match:
                undefines.append(match.group(1))
                continue

            match = self.RE_DISABLE_WARNINGS.match(flag)
            if match:
                disabled_warnings.append(match.group(1))
                continue

            match = self.RE_WARN_AS_ERROR.match(flag)
            if match:
                warn_as_error.append(match.group(1))
                continue

            match = self.RE_PROGRAM_DATABASE.match(flag)
            if match:
                tool_compiler.set('ProgramDataBaseFileName', match.group(1))
                continue

            print 'Unknown CXXFLAG: %s' % flag

        if len(defines):
            tool_compiler.set('PreprocessorDefinitions', ';'.join(defines))

        if len(undefines):
            tool_compiler.set('UndefinePreprocessorDefinitions', ';'.join(undefines))

        if len(disabled_warnings):
            tool_compiler.set('DisableSpecificWarnings', ';'.join(disabled_warnings))

        if len(warn_as_error):
            # TODO is there an attribute for /we?
            for s in warn_as_error:
                additional.append('/we%s' % s)

        def sanitize_path(path):
            # TODO should discover path prefixes and normalize to absolute
            # paths using variables inherited from property sheet
            if path == '.':
                return '$(MOZ_OBJ_DIR)\%s' % reldir

            if isabs(path):
                return path

            return '$(MOZ_OBJ_DIR)\%s\%s' % ( reldir, path )

        if len(includes):
            tool_compiler.set('AdditionalIncludeDirectories',
                              ';'.join(map(sanitize_path, includes)))

        if len(force_includes):
            tool_compiler.set('ForcedIncludeFiles',
                              ';'.join(map(sanitize_path, force_includes)))

        if len(additional):
            tool_compiler.set('AdditionalOptions', ';'.join(additional))

        configuration.append(tool_compiler)

        if len(mkdir):
            for dir in mkdir:
                pre_build_commands.append('mkdir "%s"' % dir)

        if len(pre_copy):
            for source, dest in pre_copy.iteritems():
                pre_build_commands.append('copy "%s" "%s"' % ( source, dest ))

        if len(pre_build_commands):
            tool_prebuild = Element('Tool', Name='VCPreBuildEventTool')
            tool_prebuild.set('CommandLine', '\r\n'.join(pre_build_commands))

            configuration.append(tool_prebuild)

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
                file = Element('File', RelativePath=join(source_dir, f))

                # The IDL builder in Visual Studio doesn't play nice with our
                # IDL's. So, we call out to our custom Python IDL builder for
                # all IDL files.
                fc = Element('FileConfiguration', Name='Build|Win32')

                includes = [ source_dir ]
                includes.extend(idl_includes)

                s = [ '-I%s' % p for p in includes ]
                out_path = '%s\\$(InputName).h' % idl_out_dir

                # TODO possibly consider AdditionalDependencies attribute, if
                # we can compute that
                tool = Element('Tool',
                    Name='VCCustomBuildTool',
                    CommandLine='$(IDL_HEADER) %s -o %s $(InputPath)' % (
                        ' '.join(s), out_path
                    ),
                    Outputs='%s\\$(InputName).h' % idl_out_dir,
                    Description='Converting IDL for $(InputName)'
                )

                fc.append(tool)
                file.append(fc)
                filter_idl.append(file)

            files.append(filter_idl)

        root.append(files)

        root.append(Element('Globals'))

        s = xml.etree.ElementTree.tostring(root, encoding='utf-8')
        return (s, id, name)