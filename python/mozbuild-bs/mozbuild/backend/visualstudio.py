# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

import os
import re
import uuid
import xml.etree.ElementTree

from xml.etree.ElementTree import Element

import mozbuild.frontend.data as data

from mozbuild.backend.base import BackendBase
from mozbuild.backend.utils import substitute_makefile

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

class VisualStudioBackend(BackendBase):
    """Backend that produces Visual Studio project files."""

    def __init__(self, *args):
        BackendBase.__init__(self, *args)

        self._makefiles = None

        self.version = '2008'
        self.pymake = os.path.join(self.srcdir, 'build', 'pymake', 'make.py')

    @property
    def makefiles(self):
        """TODO this was copied from hybridmake. DRY violation."""
        if self._makefiles is None:
            self._makefiles = []

            for makefile in self.frontend.makefiles.makefiles():
                substitute_makefile(makefile, self.frontend)
                self._makefiles.append(makefile)
                yield makefile

            return

        for m in self._makefiles:
            yield m

    def _generate(self):
        out_dir = os.path.join(self.objdir, 'msvc')
        self.mkdir(out_dir)

        ctx = {
            'projects': {},
            'library_ids': set(),
        }
        for makefile in self.makefiles:
            try:
                result = self._process_makefile(makefile, ctx)
            except Exception as ex:
                print ex

        solution_path = os.path.join(out_dir, 'mozilla.sln')
        with open(solution_path, 'w') as fh:
            self._write_solution(ctx, fh)

    def _process_makefile(self, makefile, ctx):
        out_dir = os.path.join(self.objdir, 'msvc')

        for obj in makefile.get_data_objects():
            result = None

            if isinstance(obj, data.LibraryInfo):
                result = self._handle_library_info(makefile, obj)

            if not result:
                continue

            filename = os.path.join(out_dir, 'lib_%s.vcproj' % result[2])
            self.add_generate_output_file(filename)

            with open(filename, 'wb') as fh:
                fh.write(result[0])

            ctx['projects'][result[1]] = {
                'id': result[1],
                'name': result[2],
                'filename': filename,
            }

    def _handle_library_info(self, makefile, obj):
        return VisualStudioBackend.write_vs_project(self.version, obj.name,
            'static',
            cpp_sources=obj.cpp_sources, c_sources=obj.c_sources,
            c_flags=obj.compile_cflags.split())

    def _write_solution(self, ctx, fh):
        version = visual_studio_product_to_internal_version(self.version, True)
        solution_id = str(uuid.uuid1())

        # Visual Studio seems to require this header.
        print >>fh, 'Microsoft Visual Studio Solution File, Format Version %s' % version

        # Write out entries for each project.
        for project in ctx['projects'].itervalues():
            print >>fh, 'Project("{%s}") = "%s", "%s", "{%s}"' % (
                solution_id, project['name'], project['filename'], project['id'])

            # TODO dependencies.

            print >>fh, 'EndProject'

        # The Global section defines configurations.
        print >>fh, 'Global'
        print >>fh, '\tGlobalSection(SolutionConfigurationPlatforms) = preSolution'
        print >>fh, '\t\tBuild|Win32 = Build|Win32'
        print >>fh, '\tEndGlobalSection'
        print >>fh, '\tGlobalSection(ProjectConfiguration) = postSolution'
        for project in ctx['projects'].itervalues():
            print >>fh, '\t\t{%s}.Build.ActiveCfg = Build|Win32' % project['id']
            print >>fh, '\t\t{%s}.Build.Build.0 = Build|Win32' % project['id']
        print >>fh, '\tEndGlobalSection'
        print >>fh, 'EndGlobal'

    def _build(self):
        pass

    @staticmethod
    def write_vs_project(version, name, project_type,
        cpp_sources=None, c_sources=None, c_flags=None):

        if c_flags is None:
            c_flags = []

        project_id = str(uuid.uuid1())

        root = Element('VisualStudioProject', attrib={
            'ProjectType': 'Visual C++',
            'Version': visual_studio_product_to_internal_version(version, False),
            'Name': name,
            'ProjectGUID': project_id,
            'RootNamespace': 'mozilla',
            'Keyword': 'Win32Proj',
        })

        platforms = Element('Platforms')
        platforms.append(Element('Platform', Name='Win32'))
        root.append(platforms)
        root.append(Element('ToolFiles'))

        configuration_type = None
        use_make = False
        static = False
        shared = False

        if project_type == 'custom':
            configuration_type = '0'
            use_make = True
        elif project_type == 'shared':
            configuration_type = '2'
            shared = True
        elif project_type == 'static':
            configuration_type = '4'
            static = True
        elif project_type == 'utility':
            configuration_type = '10'

        configurations = Element('Configurations')
        configuration = Element('Configuration',
            Name='Build|Win32',
            ConfigurationType=configuration_type,
            CharacterSet='1',
            #InheritedPropertySheets='.\mozilla.vsprops'
        )

        # Parse compiler flags into project settings.
        # http://msdn.microsoft.com/en-us/library/microsoft.visualstudio.vcprojectengine.vcclcompilertool.aspx
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

            if i == len(c_flags):
                break

            flag = c_flags[i]
            lower = flag.lower()

            # Force compilation as C (-tc) or C++ (-tp)
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
                tool_compiler.set('RuntimeLibrary', 'O')
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
                assert(i < len(c_flags))
                force_includes.append(c_flags[i+1])
                i += 1
                continue

            elif flag.startswith('-I'):
                includes.append(flag[2:])
                continue

            elif flag.startswith('-W'):
                tool_compiler.set('WarningLevel', flag[2:])
                continue

            elif flag.startswith('-wd'):
                disabled_warnings.append(flag[3:])
                continue

            elif flag.startswith('-D'):
                defines.append(flag[2:])
                continue
            elif flag.startswith('-U'):
                undefines.append(flag[2:])
                continue

            elif flag.startswith('-we'):
                warn_as_error.append(flag[3:])
                continue

            elif flag.startswith('-Fd'):
                tool_compiler.set('ProgramDatabaseFileName', flag[3:])
                continue

            print 'Unhandled compiler flag: %s' % flag

        if len(defines):
            tool_compiler.set('PreprocessorDefinitions', ';'.join(defines))

        if len(undefines):
            tool_compiler.set('UndefinePreprocessorDefinitions',
                ';'.join(undefines))

        if len(warn_as_error):
            # TODO is there an attribute for /we?
            additional.extend(['/we%s' % e for e in warn_as_error])

        if len(includes):
            tool_compiler.set('AdditionalIncludeDirectories',
                ';'.join(includes))

        if len(force_includes):
            tool_compiler.set('ForcedIncludeFiles',
                ';'.join(force_includes))

        if len(additional):
            tool_compiler.set('AdditionalOptions', ' '.join(additional))

        configuration.append(tool_compiler)

        # TODO handle linker options

        # TODO handle pre commands

        configurations.append(configuration)
        root.append(configurations)

        # Now add files to the project.
        files = Element('Files')
        sources = set(cpp_sources) | set(c_sources)
        if len(sources):
            filter_source = Element('Filter',
                Name='Source Files',
                Filter='cpp;c;cc;cxx',
                UniqueIdentifier=str(uuid.uuid1())
            )

            for source in sources:
                filter_source.append(Element('File', RelativePath=source))

            files.append(filter_source)

        # TODO Headers
        # TODO IDL

        root.append(files)

        root.append(Element('Globals'))
        s = xml.etree.ElementTree.tostring(root, encoding='utf-8')

        return (s, project_id, name)
