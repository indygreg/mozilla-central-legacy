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
# The Initial Developer of the Original Code is Mozilla Foundation.
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

# This file contains classes and methods that are specific to Visual Studio.

from os.path import isabs, join
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

        mkdir = []
        pre_copy = {}
        headers=[]
        for namespace, exports in library['exports'].iteritems():
            mkdir.append(join('$(MOZ_OBJ_DIR)', 'dist', 'include', namespace))
            for export in exports:
                dest = join('$(MOZ_OBJ_DIR)', 'dist', 'include', namespace, export)
                pre_copy[join('$(MOZ_SOURCE_DIR)', library['reldir'], export)] = dest
                headers.append(export)

        return self.build_project(
            version=version,
            name=library['normalized_name'],
            type=type,
            dir=library['dir'],
            reldir=library['reldir'],
            source_dir=library['srcdir'],
            cpp_sources=library['cppsrcs'],
            headers=headers,
            idl_sources=library['xpidlsrcs'],
            idl_out_dir=join(library['objtop'], 'dist', 'include'),
            idl_includes=[ join(library['objtop'], 'dist', 'idl') ],
            defines=library['defines'],
            cxxflags=library['cxxflags'],
            mkdir=mkdir,
            pre_copy=pre_copy,
        )

    def build_project_for_generic(self, makefile, version='2008'):
        '''Takes a MozillaMakefile and produces a project file

        This version is called when we don't know how to process the Makefile.
        It simply calls out to PyMake.
        '''

        return self.build_project(
            version=version,
            name='%s_DUMMY' % makefile.get_transformed_reldir(),
            dir=makefile.dir,
            source_dir=makefile.get_source_dir(),
            defines=makefile.get_variable_string('DEFINES'),
        )

    def build_project(self, version=None, name=None, dir=None, reldir=None,
                      type='custom',
                      source_dir=None,
                      cpp_sources=[],
                      c_sources=[],
                      headers=[],
                      idl_sources=[], idl_out_dir=None, idl_includes=[],
                      defines='', cxxflags=[],
                      pre_commands=[],
                      pre_copy={}, mkdir=[],

                      # Linker params
                      shared_library=None,
                      link_library_dependencies=True,
                      link_dependencies=[],
                      linker_generate_manifest=True,
                      linker_link_library_dependency_inputs=False,
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

          c_sources  list
                     C source files for this project

          headers  list
                   Header files. Should be relative paths to source_dir.

          idl_sources  list
                       IDL source files

          idl_out_dir  string
                       Where generated IDL files should be placed

          idl_includes  list
                        List of additional paths in which IDLs look for
                        included files.

          defines  string
                   Preprocessor definitions

          cxxflags  list
                    Set of compiler flags. These will be parsed and converted
                    to project parameters. If unknown, they will be preserved
                    on the command line.

          pre_commands list
                    List of commands to run before the build starts.

          pre_copy  dictionary
                    Set of files to copy before the build starts. Keys are
                    source filenames. Values are destination filenames.

          mkdir  list
                 List of directories to create before build.

          shared_library  string
                          Filename of generated shared library file.

          link_library_dependencies  bool
                                     Whether to link library dependencies by default.

          link_dependencies  list
                             Additional filenames to link against.

          linker_generate_manifest  bool
                                    Whether to generate a library manifest

          linker_link_dependency_inputs  bool
                                         If true, links inputs to dependencies
                                         instead of output
        '''

        if not version:
            raise Exception('version must be specified')

        if not name:
            raise Exception('name must be specified')

        if not dir:
            raise Exception('dir must be specified')

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
        shared = False

        if type == 'custom':
            configuration_type = '0'
            use_make = True
        elif type == 'shared':
            shared = True
            configuration_type = '2'
            assert(reldir)
            assert(shared_library)
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
            elif lower == '-o2':
                tool_compiler.set('Optimization', '2')
                continue
            elif lower == '-oy':
                tool_compiler.set('OmitFramePointers', 'true')
                continue
            elif flag == '-GF':
                tool_compiler.set('StringPooling', 'true')
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

        # Handle linker options.
        if shared:
            tool_linker = Element('Tool', Name='VCLinkerTool')
            tool_linker.set('OutputFile', shared_library)

            # library dependencies are linked by default
            if not link_library_dependencies:
                tool_linker.set('LinkLibraryDependencies', 'false')

            if len(link_dependencies):
                tool_linker.set('AdditionalDependencies', ' '.join(link_dependencies))

            if linker_link_library_dependency_inputs:
                tool_linker.set('UseLibraryDependencyInputs', 'true')

            if not linker_generate_manifest:
                tool_linker.set('GenerateManifest', 'false')

            configuration.append(tool_linker)

        if len(pre_commands):
            pre_build_commands.extend(pre_commands)

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
        if len(cpp_sources) or len(c_sources):
            filter_source = Element('Filter',
                Name='Source Files',
                Filter='cpp;c;cc;cxx',
                UniqueIdentifier=str(uuid1())
            )
            for f in cpp_sources:
                filter_source.append(Element('File', RelativePath=join(source_dir, f)))

            for f in c_sources:
                filter_source.append(Element('File', RelativePath=join(source_dir, f)))

            files.append(filter_source)

        headers.sort()
        if len(headers):
            filter_headers = Element('Filter',
                Name='Header Files',
                Filter='h;hpp;hxx',
                UniqueIdentifier=str(uuid1())
            )
            for f in headers:
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