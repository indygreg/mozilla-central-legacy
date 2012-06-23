# This Source Code Form is subject to the terms of the Mozilla Public
# License, v. 2.0. If a copy of the MPL was not distributed with this file,
# You can obtain one at http://mozilla.org/MPL/2.0/.

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
        """Takes a library info dict and converts to a project file"""

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
        """Takes a MozillaMakefile and produces a project file

        This version is called when we don't know how to process the Makefile.
        It simply calls out to PyMake.
        """

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
        """Convert parameters into a Visual Studio Project File string.

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
        """

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

    def build_visual_studio_files(self, python=None, version='2008', pymake=None):
        """Build Visual Studio files for the tree

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
        """
        if pymake is None:
            pymake = join(self.get_top_source_directory(), 'build', 'pymake', 'make.py')

        if python is None:
            # TODO try to find by environment
            raise Exception('Could not find Python')

        builder = VisualStudioBuilder()
        outdir = join(self.dir, 'msvc')

        if not exists(outdir):
            mkdir(outdir)

        projects = {}

        # maps files to be copied in the top project, which always gets built
        top_copy = {
            '$(MOZ_OBJ_DIR)\\mozilla-config.h': '$(MOZ_OBJ_DIR)\\dist\\include\\mozilla-config.h',
        }

        strversion = visual_studio_product_to_internal_version(version, True)

        def handle_project(project, id, name, dependencies=[]):
            filename = '%s.vcproj' % name
            projfile = join(outdir, filename)

            with open(projfile, 'w') as fh:
                fh.write(project)

            entry = {
                'id':           id,
                'name':         name,
                'filename':     filename,
                'dependencies': dependencies,
            }

            projects[id] = entry

        # Handle NSPR as a one-off, as it doesn't conform.
        def process_nspr():
            def handle_nspr_makefile(m):
                local_children = []

                # recurse immediately
                for dir in m.get_dirs():
                    m2 = self.get_dir_makefile(join(m.dir, dir))[0]
                    child_project = handle_nspr_makefile(m2)
                    if child_project:
                        local_children.append(child_project)

                # now handle the NSPR logic
                headers = []
                srcdir = m.get_variable_string('srcdir')
                for header in m.get_variable_split('HEADERS'):
                    if header.find(srcdir) == 0:
                        headers.append(header[len(srcdir)+1:])
                    else:
                        headers.append(header)

                sources = m.get_variable_split('CSRCS')

                # RELEASE_HEADERS get copied to output directory
                release_headers = m.get_variable_split('RELEASE_HEADERS')

                header_dist_dir = m.get_variable_string('dist_includedir')

                # bad code alert!
                if m.get_reldir() == 'pr\\include\\obsolete':
                    header_dist_dir = join(header_dist_dir, 'obsolete')
                elif m.get_reldir() == 'pr\\include\\private':
                    header_dist_dir = join(header_dist_dir, 'private')

                pre_copy = {}
                for header in release_headers:
                    dest = join(header_dist_dir, basename(header)).replace('/', '\\')
                    pre_copy[header.replace('/', '\\')] = dest

                name = 'nspr'
                parent = True

                type = 'custom'
                if m.get_reldir():
                    type = 'static'
                    name = 'nspr_%s' % m.get_reldir().replace('\\', '_')
                    parent = False

                if not len(sources):
                    type = 'utility'

                # ignore nspr/config b/c we don't need it (yet)
                if name == 'nspr_config':
                    return None
                elif name == 'nspr_pr_src':
                    # for some reason this Makefile pulls in sources compiled
                    # elsewhere
                    sources = []

                flags = m.get_variable_split('CFLAGS')
                mkdir = []

                # plvrsion.c looks for a header in the output directory
                if 'plvrsion.c' in sources:
                    flags.append('-I%s' % m.get_variable_string('OBJDIR'))

                shared_library = None
                library_dependencies = []

                # For shared libraries, the link command in the simple case is:
                # $(LINK_DLL) -MAP $(DLLBASE) $(DLL_LIBS) $(EXTRA_LIBS) $(OBJS) $(RES)
                # This comes from nsprpub's rules.mk when building the
                # $(SHARED_LIBRARY) target.
                if m.has_variable('LIBRARY_NAME'):
                    type = 'shared'
                    shared_library = '$(IntDir)\%s%s.dll' % ( m.get_variable_string('LIBRARY_NAME'),
                                                              m.get_variable_string('LIBRARY_VERSION'))

                    library_dependencies.extend(m.get_variable_split('EXTRA_LIBS'))

                    #for v in ('LINK_DLL', 'DLLBASE', 'DLL_LIBS', 'RES'):
                    #    print '%s: %s' % ( v, m.get_variable_split(v) )

                xml, id, project_name = builder.build_project(
                    version=version,
                    name=name,
                    dir=m.dir,
                    source_dir=m.get_variable_string('srcdir'),
                    reldir=join('nsprpub', m.get_reldir()),
                    type=type,
                    headers=headers,
                    c_sources=sources,
                    cxxflags=flags,
                    mkdir=mkdir,
                    pre_copy=pre_copy,

                    shared_library=shared_library,
                    link_dependencies=library_dependencies,
                    linker_link_library_dependency_inputs=True,
                    linker_generate_manifest=False, # TODO support this
                )

                dependencies = local_children

                # Ensure include files are copied before compilation.
                if project_name.find('src') != -1:
                    dependencies.append('nspr_pr_include')

                if project_name.find('nspr_lib') == 0:
                    dependencies.append('nspr_pr_src')

                dependencies.append('nspr_bld_header')

                print 'Writing NSPR project for %s' % project_name
                handle_project(xml, id, project_name, dependencies)

                return project_name

            m = self.get_dir_makefile('nsprpub')[0]
            handle_nspr_makefile(m)

            # NSPR has some special build events to copy certain files, etc.
            # We emulate this using a special project which does all this as
            # pre-build events. In the ideal world, these actions would be as
            # custom builders on files in the project. That's a little effort,
            # so we go the easy route for now.
            #
            # NSPR produces a set of auto-generated .h files. We create these
            # files as build events.
            # TODO we could probably put these commands on the projects they
            # are closest to.
            now = time()

            # Y U not use GMT???
            build_string = strftime('%Y-%m-%d %H:%M:%S', localtime(now))
            t = int(int(now) * 1000000 + (now - int(now)) * 1000000)
            build_time = '%si64' % t

            out_paths = {
                'pr\\src\\_pr_bld.h': 'nspr4.dll',
                'lib\\libc\\src\\_pl_bld.h': 'plc4.dll',
                'lib\\ds\\_pl_bld.h': 'plds4.dll',
            }

            commands = []
            for path, name in out_paths.iteritems():
                out_file = '$(MOZ_OBJ_DIR)\\nsprpub\\%s' % path
                commands.append('echo #define _BUILD_STRING "%s" > %s' % ( build_string, out_file ))
                commands.append('echo #define _BUILD_TIME %s >> %s' % ( build_time, out_file ))
                commands.append('echo #define _PRODUCTION "%s" >> %s' % ( name, out_file ))

            copies = {}

            # NSPR also has a set of per-platform .cfg files. We copy these to
            # the output directory.
            md_makefile = self.get_dir_makefile('nsprpub\\pr\\include\\md')[0]
            for config in md_makefile.get_variable_split('CONFIGS'):
                source = config.replace('/', '\\')
                dest = '$(MOZ_OBJ_DIR)\\dist\\include\\nspr\\md\\%s' % basename(config)
                copies[source] = dest

            # NSPR takes one of these config files and renames it to prcpucfg.h
            source = '$(MOZ_SOURCE_DIR)\\nsprpub\\pr\\include\\md\\%s' % m.get_variable_string('MDCPUCFG_H')
            copies[source] = '$(MOZ_OBJ_DIR)\\dist\\include\\nspr\\prcpucfg.h'

            xml, id, project_name = builder.build_project(
                version=version,
                name='nspr_bld_header',
                type='utility',
                dir=m.dir,
                pre_commands=commands,
                pre_copy=copies,
            )
            handle_project(xml, id, project_name, ['top'])

        process_nspr()

        # create parent project that does initialization
        # TODO we could probably do this more intelligently
        proj, id, name = builder.build_project(
            version=version,
            name='top',
            type='utility',
            dir=self.topsourcedir,
            source_dir=self.topsourcedir,
            mkdir=[
                '$(MOZ_OBJ_DIR)\\dist\\bin',
                '$(MOZ_OBJ_DIR)\\dist\\idl',
                '$(MOZ_OBJ_DIR)\\dist\\include\\nspr\\md',
                '$(MOZ_OBJ_DIR)\\dist\\include\\nspr\\obsolete',
                '$(MOZ_OBJ_DIR)\\dist\\include\\nspr\\private',
                '$(MOZ_OBJ_DIR)\\dist\\lib',
            ],
            pre_copy=top_copy,
        )
        handle_project(proj, id, name)

        # calculate dependencies
        project_name_id_map = {}
        project_dependencies = {}
        for project in projects.itervalues():
            project_name_id_map[project['name']] = project['id']

        for project in projects.itervalues():
            depends = []
            for name in project['dependencies']:
                depends.append(project_name_id_map[name])

            if len(depends):
                project_dependencies[project['id']] = depends

        # now produce the Solution file
        # TODO move to visualstudio module
        slnpath = join(outdir, 'mozilla.sln')
        configid = str(uuid1())
        with open(slnpath, 'w') as fh:
            # Visual Studio seems to require this header
            print >>fh, 'Microsoft Visual Studio Solution File, Format Version %s' % strversion

            # write out entries for each project
            for project in projects.itervalues():
                print >>fh, 'Project("{%s}") = "%s", "%s", "{%s}"' % (
                    configid, project['name'], project['filename'], project['id']
                )

                if project['id'] in project_dependencies:
                    print >>fh, '\tProjectSection(ProjectDependencies) = postProject'
                    for id in project_dependencies[project['id']]:
                        print >>fh, '\t\t{%s} = {%s}' % ( id, id )
                    print >>fh, '\tEndProjectSection'

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



        # The following was left over from the old single file extractor
        #info = self.get_module_data(dir)
        #names = []
        #for library in info['libraries']:
        #    proj, id, name = builder.build_project_for_library(
        #        library, name, version=version
        #    )
        #
        #    handle_project(proj, id, name)
        #    names.append(name)
        #
        #    for idl in library['xpidlsrcs']:
        #        source = join('$(MOZ_SOURCE_DIR)', library['reldir'], idl)
        #        top_copy[source] = join('$(MOZ_OBJ_DIR)', 'dist', 'idl', idl)
        #
        #if len(names):
        #    print 'Wrote projects for libraries: %s' % ' '.join(names)
        #
        #for path in info['unhandled']:
        #    print 'Writing generic project for %s' % path
        #    m2 = self.get_dir_makefile(path)[0]
        #
        #    proj, id, name = builder.build_project_for_generic(
        #        m2, version=version
        #    )
        #    handle_project(proj, id, name)

        # fall back to generic case
        #print 'Writing generic project for %s' % directory
        #proj, id, name = builder.build_project_for_generic(
        #  m, version=version
        #)
        #handle_project(proj, id, name)
