/* -*- Mode: C++; tab-width: 8; indent-tabs-mode: nil; c-basic-offset: 4 -*-
 * vim: set ts=8 sw=4 et tw=99:
 *
 * ***** BEGIN LICENSE BLOCK *****
 * Version: MPL 1.1/GPL 2.0/LGPL 2.1
 *
 * The contents of this file are subject to the Mozilla Public License Version
 * 1.1 (the "License"); you may not use this file except in compliance with
 * the License. You may obtain a copy of the License at
 * http://www.mozilla.org/MPL/
 *
 * Software distributed under the License is distributed on an "AS IS" basis,
 * WITHOUT WARRANTY OF ANY KIND, either express or implied. See the License
 * for the specific language governing rights and limitations under the
 * License.
 *
 * The Original Code is Mozilla Communicator client code, released
 * March 31, 1998.
 *
 * The Initial Developer of the Original Code is
 * Netscape Communications Corporation.
 * Portions created by the Initial Developer are Copyright (C) 1998
 * the Initial Developer. All Rights Reserved.
 *
 * Contributor(s):
 *
 * Alternatively, the contents of this file may be used under the terms of
 * either of the GNU General Public License Version 2 or later (the "GPL"),
 * or the GNU Lesser General Public License Version 2.1 or later (the "LGPL"),
 * in which case the provisions of the GPL or the LGPL are applicable instead
 * of those above. If you wish to allow use of your version of this file only
 * under the terms of either the GPL or the LGPL, and not to allow others to
 * use your version of this file under the terms of the MPL, indicate your
 * decision by deleting the provisions above and replace them with the notice
 * and other provisions required by the GPL or the LGPL. If you do not delete
 * the provisions above, a recipient may use your version of this file under
 * the terms of any one of the MPL, the GPL or the LGPL.
 *
 * ***** END LICENSE BLOCK ***** */

// [gps] This file contains a very crude executor for JavaScript files tailored
// for use in the JIT test suite. The coding quality is horrible and it needs
// lots of love. It is meant as a proof-of-concept, not production code.

#include "jit-test/jsshell-code-that-should-be-in-a-library-but-isnt.hpp"

#include <iostream>
#include <map>
#include <string>
#include <vector>

#include <stdio.h>

using ::std::cerr;
using ::std::cout;
using ::std::cin;
using ::std::endl;
using ::std::string;
using ::std::map;
using ::std::vector;

string readFile(string filename) {
    FILE *f = fopen(filename.c_str(), "r");
    if (!f) {
        cerr << "Error opening file: " << filename << endl;
        return "";
    }
    fseek(f, 0, SEEK_END);
    long length = ftell(f);
    fseek(f, 0, SEEK_SET);
    string s(length, '\0');
    fread((void *)s.c_str(), length, 1, f);
    fclose(f);

    return s;
}

void readTestFiles(map<string, string> &files) {
    string line;

    while(getline(cin, line)) {
        files[line] = readFile(line);
    }

    return;
}

int RunTest(JSRuntime *runtime, int options, bool debug, string filename, string content,
             string prologScript, string prologFilename, string prologContent, char *env[]) {
    static int globalOptions = JSOPTION_VAROBJFIX;

    //cerr << options << " " << filename << endl;

    JSContext *ctx = JS_NewContext(runtime, 8192);
    if (!ctx) {
        cerr << "Could not initialize new context." << endl;
        return 1;
    }

    /*
    JSShellContextData *data = NewContextData();
    if (!data) {
        cerr << "Could not initialize context data" << endl;
        return 1;
    }

    JS_SetContextPrivate(ctx, data);
    */

    JS_SetErrorReporter(ctx, reportError);
    JS_SetVersion(ctx, JSVERSION_LATEST);

    JS_SetOptions(ctx, globalOptions | options);

    JS_SetGCParameterForThread(ctx, JSGC_MAX_CODE_CACHE_BYTES, 16 * 1024 * 1024);

    JS_BeginRequest(ctx);
    JSObject *global = JS_NewCompartmentAndGlobalObject(ctx, &global_class, NULL);
    if (!global) {
        cerr << "Could not create global object." << endl;
        return 1;
    }

    if (!JS_InitStandardClasses(ctx, global)) {
        cerr << "Could not initialize standard classes." << endl;
        return 1;
    }

    if (!JS_DefineFunctions(ctx, global, functions)) {
        cerr << "Could not define functions." << endl;
        return 1;
    }

    JSObject *envobj = JS_DefineObject(ctx, global, "environment", &env_class, NULL, 0);
    if (!envobj || !JS_SetPrivate(ctx, envobj, env)) {
        cerr << "Could not define environment object." << endl;
        return 1;
    }

    JS_SetRuntimeDebugMode(JS_GetRuntime(ctx), debug);
    JS_SetDebugMode(ctx, debug);

    jsval rv;

    // execute script prolog
    if (!JS_EvaluateScript(ctx, global, prologScript.c_str(), prologScript.length(), "-e", 1, &rv)) {
        cerr << "Error executing prolog script." << endl;
        return 1;
    }

    if (!JS_EvaluateScript(ctx, global, prologContent.c_str(), prologContent.length(),
                           prologFilename.c_str(), 1, &rv)) {
        cerr << "Error executing prolog file." << endl;
        return 1;
    }

    if (!JS_EvaluateScript(ctx, global, content.c_str(), content.length(),
                           filename.c_str(), 0, &rv)) {
        cerr << "Error executing test: " << filename << endl;
        cerr.flush();
    }

    JS_EndRequest(ctx);
    JS_DestroyContext(ctx);

    return 0;
}

int main(int argc, const char *argv[], char *env[])
{
    if (argc < 3) {
        cout << "Usage: jit-test-runner <prolog script> <prolog script filename>" << endl;
        return 1;
    }

    string prologScript = argv[1];
    string prologFilename = argv[2];
    string prologContent = readFile(prologFilename);

    map<string, string> files;
    readTestFiles(files);

    JSRuntime *runtime = JS_NewRuntime(1024 * 1048576); // 1GB
    if (!runtime) {
        cerr << "Could not create runtime." << endl;
        return 1;
    }

    JS_SetGCParameter(runtime, JSGC_MODE, JSGC_MODE_COMPARTMENT);
    JS_SetTrustedPrincipals(runtime, &shellTrustedPrincipals);
    JS_SetRuntimeSecurityCallbacks(runtime, &securityCallbacks);

    vector<int> options;
    options.push_back(0);                  // Default options
    options.push_back(JSOPTION_METHODJIT); // -m
    options.push_back(JSOPTION_JIT);       // -j
    options.push_back(JSOPTION_METHODJIT | JSOPTION_JIT); // -m -j
    options.push_back(JSOPTION_METHODJIT | JSOPTION_JIT | JSOPTION_PROFILING); // -m -j -p
    options.push_back(JSOPTION_METHODJIT_ALWAYS | JSOPTION_METHODJIT); // -a -m
    options.push_back(JSOPTION_METHODJIT_ALWAYS | JSOPTION_METHODJIT | JSOPTION_JIT); // -a -m -j
    options.push_back(JSOPTION_METHODJIT_ALWAYS | JSOPTION_METHODJIT | JSOPTION_JIT | JSOPTION_PROFILING); // -a -m -j -p
    options.push_back(JSOPTION_TYPE_INFERENCE); // -n
    options.push_back(JSOPTION_METHODJIT | JSOPTION_TYPE_INFERENCE); // -m -n
    options.push_back(JSOPTION_JIT | JSOPTION_TYPE_INFERENCE); // -j -n
    options.push_back(JSOPTION_METHODJIT | JSOPTION_JIT | JSOPTION_TYPE_INFERENCE); // -m -j -n
    options.push_back(JSOPTION_METHODJIT | JSOPTION_JIT | JSOPTION_PROFILING | JSOPTION_TYPE_INFERENCE); // -m -j -p -n
    options.push_back(JSOPTION_METHODJIT_ALWAYS | JSOPTION_METHODJIT | JSOPTION_TYPE_INFERENCE); // -a -m -n
    options.push_back(JSOPTION_METHODJIT_ALWAYS | JSOPTION_METHODJIT | JSOPTION_JIT | JSOPTION_TYPE_INFERENCE); // -a -m -j -n
    options.push_back(JSOPTION_METHODJIT_ALWAYS | JSOPTION_METHODJIT | JSOPTION_JIT | JSOPTION_PROFILING | JSOPTION_TYPE_INFERENCE); // -a -m -j -p -n

    vector<int> debugOptions;
    debugOptions.push_back(JSOPTION_METHODJIT_ALWAYS | JSOPTION_METHODJIT); // -a -m -d
    debugOptions.push_back(JSOPTION_METHODJIT_ALWAYS | JSOPTION_METHODJIT | JSOPTION_TYPE_INFERENCE); // -a -m -d -n

    for (map<string, string>::iterator i = files.begin(); i != files.end(); i++) {
        cerr << "Executing " << i->first << endl;
        for (vector<int>::iterator option = options.begin(); option != options.end(); option++) {
            int result = RunTest(runtime, *option, false, i->first, i->second,
                         prologScript, prologFilename, prologContent, env);

            if (result) {
                return result;
            }
        }

        for (vector<int>::iterator option = debugOptions.begin(); option != debugOptions.end(); option++) {
            //cerr << "Executing in debug mode" << endl;
            int result = RunTest(runtime, *option, true, i->first, i->second,
                                 prologScript, prologFilename, prologContent, env);
            if (result) {
                return result;
            }
        }
    }

    JS_DestroyRuntime(runtime);
    JS_ShutDown();

    return 0;
}