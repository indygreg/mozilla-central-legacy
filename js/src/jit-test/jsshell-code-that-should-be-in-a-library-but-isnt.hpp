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

// [gps] The contents of this file were mostly copied from js.cpp. In the
// ideal world, many of these routines would be defined in a library so
// the wheel doesn't get reinvented.

#include "jsapi.h"
#include "jsatom.h"
#include "jsbool.h"
#include "jscntxt.h"
#include "jsdate.h"
#include "jsperf.h"
#include "jsprf.h"
#include "jsscan.h"
#include "jstypedarray.h"
#include "jsvalue.h"
#include "jswrapper.h"

#include "errno.h"

#include <iostream>
#include <string>

using ::std::cerr;
using ::std::cout;
using ::std::endl;
using ::std::string;

using namespace js;

static JSBool compileOnly = JS_FALSE;

static JSClass global_class = {
    "global", JSCLASS_GLOBAL_FLAGS,
    JS_PropertyStub, JS_PropertyStub, JS_PropertyStub, JS_StrictPropertyStub,
    JS_EnumerateStub, JS_ResolveStub, JS_ConvertStub, JS_FinalizeStub,
    JSCLASS_NO_OPTIONAL_MEMBERS
};

JSBool
ShellPrincipalsSubsume(JSPrincipals *, JSPrincipals *)
{
    return JS_TRUE;
}

JSPrincipals shellTrustedPrincipals = {
    (char *)"[shell trusted principals]",
    NULL,
    NULL,
    1,
    NULL, /* nobody should be destroying this */
    ShellPrincipalsSubsume
};

JSBool
CheckObjectAccess(JSContext *cx, JSObject *obj, jsid id, JSAccessMode mode,
                  jsval *vp)
{
    LeaveTrace(cx);
    return true;
}

JSSecurityCallbacks securityCallbacks = {
    CheckObjectAccess,
    NULL,
    NULL,
    NULL
};

// following functions copied from js.cpp. y u no defined in reusable library?
static void
ReportException(JSContext *cx)
{
    if (JS_IsExceptionPending(cx)) {
        if (!JS_ReportPendingException(cx))
            JS_ClearPendingException(cx);
    }
}

class ToString {
  public:
    ToString(JSContext *aCx, jsval v, JSBool aThrow = JS_FALSE)
      : cx(aCx), mThrow(aThrow)
    {
        mStr = JS_ValueToString(cx, v);
        if (!aThrow && !mStr)
            ReportException(cx);
        JS_AddNamedStringRoot(cx, &mStr, "Value ToString helper");
    }
    ~ToString() {
        JS_RemoveStringRoot(cx, &mStr);
    }
    JSBool threw() { return !mStr; }
    jsval getJSVal() { return STRING_TO_JSVAL(mStr); }
    const char *getBytes() {
        if (mStr && (mBytes.ptr() || mBytes.encode(cx, mStr)))
            return mBytes.ptr();
        return "(error converting value)";
    }
  private:
    JSContext *cx;
    JSString *mStr;
    JSBool mThrow;
    JSAutoByteString mBytes;
};

class IdStringifier : public ToString {
public:
    IdStringifier(JSContext *cx, jsid id, JSBool aThrow = JS_FALSE)
    : ToString(cx, js::IdToJsval(id), aThrow)
    { }
};

static JSBool
env_setProperty(JSContext *cx, JSObject *obj, jsid id, JSBool strict, jsval *vp)
{
/* XXX porting may be easy, but these don't seem to supply setenv by default */
#if !defined XP_OS2 && !defined SOLARIS
    int rv;

    IdStringifier idstr(cx, id, JS_TRUE);
    if (idstr.threw())
        return JS_FALSE;
    ToString valstr(cx, *vp, JS_TRUE);
    if (valstr.threw())
        return JS_FALSE;
#if defined XP_WIN || defined HPUX || defined OSF1
    {
        char *waste = JS_smprintf("%s=%s", idstr.getBytes(), valstr.getBytes());
        if (!waste) {
            JS_ReportOutOfMemory(cx);
            return JS_FALSE;
        }
        rv = putenv(waste);
#ifdef XP_WIN
        /*
         * HPUX9 at least still has the bad old non-copying putenv.
         *
         * Per mail from <s.shanmuganathan@digital.com>, OSF1 also has a putenv
         * that will crash if you pass it an auto char array (so it must place
         * its argument directly in the char *environ[] array).
         */
        JS_smprintf_free(waste);
#endif
    }
#else
    rv = setenv(idstr.getBytes(), valstr.getBytes(), 1);
#endif
    if (rv < 0) {
        JS_ReportError(cx, "can't set env variable %s to %s", idstr.getBytes(), valstr.getBytes());
        return JS_FALSE;
    }
    *vp = valstr.getJSVal();
#endif /* !defined XP_OS2 && !defined SOLARIS */
    return JS_TRUE;
}

static JSBool
env_enumerate(JSContext *cx, JSObject *obj)
{
    static JSBool reflected;
    char **evp, *name, *value;
    JSString *valstr;
    JSBool ok;

    if (reflected)
        return JS_TRUE;

    for (evp = (char **)JS_GetPrivate(cx, obj); (name = *evp) != NULL; evp++) {
        value = strchr(name, '=');
        if (!value)
            continue;
        *value++ = '\0';
        valstr = JS_NewStringCopyZ(cx, value);
        if (!valstr) {
            ok = JS_FALSE;
        } else {
            ok = JS_DefineProperty(cx, obj, name, STRING_TO_JSVAL(valstr),
                                   NULL, NULL, JSPROP_ENUMERATE);
        }
        value[-1] = '=';
        if (!ok)
            return JS_FALSE;
    }

    reflected = JS_TRUE;
    return JS_TRUE;
}

static JSBool
env_resolve(JSContext *cx, JSObject *obj, jsid id, uintN flags,
            JSObject **objp)
{
    JSString *valstr;
    const char *name, *value;

    if (flags & JSRESOLVE_ASSIGNING)
        return JS_TRUE;

    IdStringifier idstr(cx, id, JS_TRUE);
    if (idstr.threw())
        return JS_FALSE;

    name = idstr.getBytes();
    value = getenv(name);
    if (value) {
        valstr = JS_NewStringCopyZ(cx, value);
        if (!valstr)
            return JS_FALSE;
        if (!JS_DefineProperty(cx, obj, name, STRING_TO_JSVAL(valstr),
                               NULL, NULL, JSPROP_ENUMERATE)) {
            return JS_FALSE;
        }
        *objp = obj;
    }
    return JS_TRUE;
}

typedef enum JSShellErrNum {
#define MSG_DEF(name, number, count, exception, format) \
    name = number,
#include "jsshell.msg"
#undef MSG_DEF
    JSShellErr_Limit
#undef MSGDEF
} JSShellErrNum;

JSErrorFormatString jsShell_ErrorFormatString[JSErr_Limit] = {
#define MSG_DEF(name, number, count, exception, format) \
    { format, count, JSEXN_ERR } ,
#include "jsshell.msg"
#undef MSG_DEF
};

static const JSErrorFormatString *
my_GetErrorMessage(void *userRef, const char *locale, const uintN errorNumber)
{
    if ((errorNumber > 0) && (errorNumber < JSShellErr_Limit))
        return &jsShell_ErrorFormatString[errorNumber];
    return NULL;
}

static const char *
ToSource(JSContext *cx, jsval *vp, JSAutoByteString *bytes)
{
    JSString *str = JS_ValueToSource(cx, *vp);
    if (str) {
        *vp = STRING_TO_JSVAL(str);
        if (bytes->encode(cx, str))
            return bytes->ptr();
    }
    JS_ClearPendingException(cx);
    return "<<error converting value to string>>";
}

static const struct {
    const char  *name;
    uint32      flag;
} js_options[] = {
    {"atline",          JSOPTION_ATLINE},
    {"jitprofiling",    JSOPTION_PROFILING},
    {"tracejit",        JSOPTION_JIT},
    {"methodjit",       JSOPTION_METHODJIT},
    {"methodjit_always",JSOPTION_METHODJIT_ALWAYS},
    {"relimit",         JSOPTION_RELIMIT},
    {"strict",          JSOPTION_STRICT},
    {"typeinfer",       JSOPTION_TYPE_INFERENCE},
    {"werror",          JSOPTION_WERROR},
    {"xml",             JSOPTION_XML},
};

static uint32
MapContextOptionNameToFlag(JSContext* cx, const char* name)
{
    for (size_t i = 0; i != JS_ARRAY_LENGTH(js_options); ++i) {
        if (strcmp(name, js_options[i].name) == 0)
            return js_options[i].flag;
    }

    char* msg = JS_sprintf_append(NULL,
                                  "unknown option name '%s'."
                                  " The valid names are ", name);
    for (size_t i = 0; i != JS_ARRAY_LENGTH(js_options); ++i) {
        if (!msg)
            break;
        msg = JS_sprintf_append(msg, "%s%s", js_options[i].name,
                                (i + 2 < JS_ARRAY_LENGTH(js_options)
                                 ? ", "
                                 : i + 2 == JS_ARRAY_LENGTH(js_options)
                                 ? " and "
                                 : "."));
    }
    if (!msg) {
        JS_ReportOutOfMemory(cx);
    } else {
        JS_ReportError(cx, msg);
        free(msg);
    }
    return 0;
}

static JSBool
AssertEq(JSContext *cx, uintN argc, jsval *vp)
{
    if (!(argc == 2 || (argc == 3 && JSVAL_IS_STRING(JS_ARGV(cx, vp)[2])))) {
        JS_ReportErrorNumber(cx, my_GetErrorMessage, NULL,
                             (argc < 2)
                             ? JSSMSG_NOT_ENOUGH_ARGS
                             : (argc == 3)
                             ? JSSMSG_INVALID_ARGS
                             : JSSMSG_TOO_MANY_ARGS,
                             "assertEq");
        return JS_FALSE;
    }

    jsval *argv = JS_ARGV(cx, vp);
    JSBool same;
    if (!JS_SameValue(cx, argv[0], argv[1], &same))
        return JS_FALSE;
    if (!same) {
        JSAutoByteString bytes0, bytes1;
        const char *actual = ToSource(cx, &argv[0], &bytes0);
        const char *expected = ToSource(cx, &argv[1], &bytes1);
        if (argc == 2) {
            JS_ReportErrorNumber(cx, my_GetErrorMessage, NULL, JSSMSG_ASSERT_EQ_FAILED,
                                 actual, expected);
        } else {
            JSAutoByteString bytes2(cx, JSVAL_TO_STRING(argv[2]));
            if (!bytes2)
                return JS_FALSE;
            JS_ReportErrorNumber(cx, my_GetErrorMessage, NULL, JSSMSG_ASSERT_EQ_FAILED_MSG,
                                 actual, expected, bytes2.ptr());
        }
        return JS_FALSE;
    }
    JS_SET_RVAL(cx, vp, JSVAL_VOID);
    return JS_TRUE;
}

static JSBool
Print(JSContext *cx, uintN argc, jsval *vp)
{
    jsval *argv;
    uintN i;
    JSString *str;
    char *bytes;

    argv = JS_ARGV(cx, vp);
    for (i = 0; i < argc; i++) {
        str = JS_ValueToString(cx, argv[i]);
        if (!str)
            return JS_FALSE;
        bytes = JS_EncodeString(cx, str);
        if (!bytes)
            return JS_FALSE;
        cout << (i ? " " : "");
        cout << string(bytes);
        JS_free(cx, bytes);
    }

    cout << '\n';
    cout.flush();

    JS_SET_RVAL(cx, vp, JSVAL_VOID);
    return JS_TRUE;
}

static JSBool
GC(JSContext *cx, uintN argc, jsval *vp)
{
    JSCompartment *comp = NULL;
    if (argc == 1) {
        Value arg = Valueify(vp[2]);
        if (arg.isObject())
            comp = arg.toObject().unwrap()->compartment();
    }

    size_t preBytes = cx->runtime->gcBytes;
    JS_CompartmentGC(cx, comp);

    char buf[256];
    JS_snprintf(buf, sizeof(buf), "before %lu, after %lu, break %08lx\n",
                (unsigned long)preBytes, (unsigned long)cx->runtime->gcBytes,
#ifdef HAVE_SBRK
                (unsigned long)sbrk(0)
#else
                0
#endif
                );
    *vp = STRING_TO_JSVAL(JS_NewStringCopyZ(cx, buf));
    return true;
}

static JSBool
Load(JSContext *cx, uintN argc, jsval *vp)
{
    JSObject *thisobj = JS_THIS_OBJECT(cx, vp);
    if (!thisobj)
        return JS_FALSE;

    jsval *argv = JS_ARGV(cx, vp);
    for (uintN i = 0; i < argc; i++) {
        JSString *str = JS_ValueToString(cx, argv[i]);
        if (!str)
            return false;
        argv[i] = STRING_TO_JSVAL(str);
        JSAutoByteString filename(cx, str);
        if (!filename)
            return JS_FALSE;
        errno = 0;
        uint32 oldopts = JS_GetOptions(cx);
        JS_SetOptions(cx, oldopts | JSOPTION_COMPILE_N_GO | JSOPTION_NO_SCRIPT_RVAL);
        JSObject *scriptObj = JS_CompileFile(cx, thisobj, filename.ptr());
        JS_SetOptions(cx, oldopts);
        if (!scriptObj)
            return false;

        if (!compileOnly && !JS_ExecuteScript(cx, thisobj, scriptObj, NULL))
            return false;
    }

    JS_SET_RVAL(cx, vp, JSVAL_VOID);
    return true;
}

static JSBool
Version(JSContext *cx, uintN argc, jsval *vp)
{
    jsval *argv = JS_ARGV(cx, vp);
    if (argc == 0 || JSVAL_IS_VOID(argv[0])) {
        /* Get version. */
        *vp = INT_TO_JSVAL(JS_GetVersion(cx));
    } else {
        /* Set version. */
        int32 v = -1;
        if (JSVAL_IS_INT(argv[0])) {
            v = JSVAL_TO_INT(argv[0]);
        } else if (JSVAL_IS_DOUBLE(argv[0])) {
            jsdouble fv = JSVAL_TO_DOUBLE(argv[0]);
            if (int32(fv) == fv)
                v = int32(fv);
        }
        if (v < 0 || v > JSVERSION_LATEST) {
            JS_ReportErrorNumber(cx, my_GetErrorMessage, NULL, JSSMSG_INVALID_ARGS, "version");
            return false;
        }
        *vp = INT_TO_JSVAL(JS_SetVersion(cx, JSVersion(v)));
    }
    return true;
}

static JSBool
RevertVersion(JSContext *cx, uintN argc, jsval *vp)
{
    js_RevertVersion(cx);
    JS_SET_RVAL(cx, vp, JSVAL_VOID);
    return JS_TRUE;
}

static JSBool
Options(JSContext *cx, uintN argc, jsval *vp)
{
    uint32 optset, flag;
    JSString *str;
    char *names;
    JSBool found;

    optset = 0;
    jsval *argv = JS_ARGV(cx, vp);
    for (uintN i = 0; i < argc; i++) {
        str = JS_ValueToString(cx, argv[i]);
        if (!str)
            return JS_FALSE;
        argv[i] = STRING_TO_JSVAL(str);
        JSAutoByteString opt(cx, str);
        if (!opt)
            return JS_FALSE;
        flag = MapContextOptionNameToFlag(cx, opt.ptr());
        if (!flag)
            return JS_FALSE;
        optset |= flag;
    }
    optset = JS_ToggleOptions(cx, optset);

    names = NULL;
    found = JS_FALSE;
    for (size_t i = 0; i != JS_ARRAY_LENGTH(js_options); i++) {
        if (js_options[i].flag & optset) {
            found = JS_TRUE;
            names = JS_sprintf_append(names, "%s%s",
                                      names ? "," : "", js_options[i].name);
            if (!names)
                break;
        }
    }
    if (!found)
        names = strdup("");
    if (!names) {
        JS_ReportOutOfMemory(cx);
        return JS_FALSE;
    }
    str = JS_NewStringCopyZ(cx, names);
    free(names);
    if (!str)
        return JS_FALSE;
    *vp = STRING_TO_JSVAL(str);
    return JS_TRUE;
}

static JSBool
Evaluate(JSContext *cx, uintN argc, jsval *vp)
{
    if (argc != 1 || !JSVAL_IS_STRING(JS_ARGV(cx, vp)[0])) {
        JS_ReportErrorNumber(cx, my_GetErrorMessage, NULL,
                             (argc != 1) ? JSSMSG_NOT_ENOUGH_ARGS : JSSMSG_INVALID_ARGS,
                             "evaluate");
        return false;
    }

    JSString *code = JSVAL_TO_STRING(JS_ARGV(cx, vp)[0]);

    size_t codeLength;
    const jschar *codeChars = JS_GetStringCharsAndLength(cx, code, &codeLength);
    if (!codeChars)
        return false;

    JSObject *thisobj = JS_THIS_OBJECT(cx, vp);
    if (!thisobj)
        return false;

    if ((JS_GET_CLASS(cx, thisobj)->flags & JSCLASS_IS_GLOBAL) != JSCLASS_IS_GLOBAL) {
        JS_ReportErrorNumber(cx, js_GetErrorMessage, NULL, JSMSG_UNEXPECTED_TYPE,
                             "this-value passed to evaluate()", "not a global object");
        return false;
    }

    JS_SET_RVAL(cx, vp, JSVAL_VOID);
    return JS_EvaluateUCScript(cx, thisobj, codeChars, codeLength, "@evaluate", 0, NULL);
}

static JSString *
FileAsString(JSContext *cx, const char *pathname)
{
    FILE *file;
    JSString *str = NULL;
    size_t len, cc;
    char *buf;

    file = fopen(pathname, "rb");
    if (!file) {
        JS_ReportError(cx, "can't open %s: %s", pathname, strerror(errno));
        return NULL;
    }

    if (fseek(file, 0, SEEK_END) != 0) {
        JS_ReportError(cx, "can't seek end of %s", pathname);
    } else {
        len = ftell(file);
        if (fseek(file, 0, SEEK_SET) != 0) {
            JS_ReportError(cx, "can't seek start of %s", pathname);
        } else {
            buf = (char*) JS_malloc(cx, len + 1);
            if (buf) {
                cc = fread(buf, 1, len, file);
                if (cc != len) {
                    JS_ReportError(cx, "can't read %s: %s", pathname,
                                   (ptrdiff_t(cc) < 0) ? strerror(errno) : "short read");
                } else {
                    jschar *ucbuf;
                    size_t uclen;

                    len = (size_t)cc;

                    if (!JS_DecodeUTF8(cx, buf, len, NULL, &uclen)) {
                        JS_ReportError(cx, "Invalid UTF-8 in file '%s'", pathname);
                        return NULL;
                    }

                    ucbuf = (jschar*)malloc(uclen * sizeof(jschar));
                    JS_DecodeUTF8(cx, buf, len, ucbuf, &uclen);
                    str = JS_NewUCStringCopyN(cx, ucbuf, uclen);
                    free(ucbuf);
                }
                JS_free(cx, buf);
            }
        }
    }
    fclose(file);

    return str;
}

static JSObject *
FileAsTypedArray(JSContext *cx, const char *pathname)
{
    FILE *file = fopen(pathname, "rb");
    if (!file) {
        JS_ReportError(cx, "can't open %s: %s", pathname, strerror(errno));
        return NULL;
    }

    JSObject *obj = NULL;
    if (fseek(file, 0, SEEK_END) != 0) {
        JS_ReportError(cx, "can't seek end of %s", pathname);
    } else {
        size_t len = ftell(file);
        if (fseek(file, 0, SEEK_SET) != 0) {
            JS_ReportError(cx, "can't seek start of %s", pathname);
        } else {
            obj = js_CreateTypedArray(cx, TypedArray::TYPE_UINT8, len);
            if (!obj)
                return NULL;
            char *buf = (char *) TypedArray::getDataOffset(TypedArray::getTypedArray(obj));
            size_t cc = fread(buf, 1, len, file);
            if (cc != len) {
                JS_ReportError(cx, "can't read %s: %s", pathname,
                               (ptrdiff_t(cc) < 0) ? strerror(errno) : "short read");
                obj = NULL;
            }
        }
    }
    fclose(file);
    return obj;
}

static JSBool
Run(JSContext *cx, uintN argc, jsval *vp)
{
    if (argc != 1) {
        JS_ReportErrorNumber(cx, my_GetErrorMessage, NULL, JSSMSG_INVALID_ARGS, "run");
        return false;
    }

    JSObject *thisobj = JS_THIS_OBJECT(cx, vp);
    if (!thisobj)
        return false;

    jsval *argv = JS_ARGV(cx, vp);
    JSString *str = JS_ValueToString(cx, argv[0]);
    if (!str)
        return false;
    argv[0] = STRING_TO_JSVAL(str);
    JSAutoByteString filename(cx, str);
    if (!filename)
        return false;

    const jschar *ucbuf = NULL;
    size_t buflen;
    str = FileAsString(cx, filename.ptr());
    if (str)
        ucbuf = JS_GetStringCharsAndLength(cx, str, &buflen);
    if (!ucbuf)
        return false;

    JS::Anchor<JSString *> a_str(str);
    uint32 oldopts = JS_GetOptions(cx);
    JS_SetOptions(cx, oldopts | JSOPTION_COMPILE_N_GO | JSOPTION_NO_SCRIPT_RVAL);

    int64 startClock = PRMJ_Now();
    JSObject *scriptObj = JS_CompileUCScript(cx, thisobj, ucbuf, buflen, filename.ptr(), 1);
    JS_SetOptions(cx, oldopts);
    if (!scriptObj || !JS_ExecuteScript(cx, thisobj, scriptObj, NULL))
        return false;

    int64 endClock = PRMJ_Now();
    JS_SET_RVAL(cx, vp, DOUBLE_TO_JSVAL((endClock - startClock) / double(PRMJ_USEC_PER_MSEC)));
    return true;
}

/*
 * function readline()
 * Provides a hook for scripts to read a line from stdin.
 */
static JSBool
ReadLine(JSContext *cx, uintN argc, jsval *vp)
{
#define BUFSIZE 256
    FILE *from;
    char *buf, *tmp;
    size_t bufsize, buflength, gotlength;
    JSBool sawNewline;
    JSString *str;

    from = stdin;
    buflength = 0;
    bufsize = BUFSIZE;
    buf = (char *) JS_malloc(cx, bufsize);
    if (!buf)
        return JS_FALSE;

    sawNewline = JS_FALSE;
    while ((gotlength =
            js_fgets(buf + buflength, bufsize - buflength, from)) > 0) {
        buflength += gotlength;

        /* Are we done? */
        if (buf[buflength - 1] == '\n') {
            buf[buflength - 1] = '\0';
            sawNewline = JS_TRUE;
            break;
        } else if (buflength < bufsize - 1) {
            break;
        }

        /* Else, grow our buffer for another pass. */
        bufsize *= 2;
        if (bufsize > buflength) {
            tmp = (char *) JS_realloc(cx, buf, bufsize);
        } else {
            JS_ReportOutOfMemory(cx);
            tmp = NULL;
        }

        if (!tmp) {
            JS_free(cx, buf);
            return JS_FALSE;
        }

        buf = tmp;
    }

    /* Treat the empty string specially. */
    if (buflength == 0) {
        *vp = feof(from) ? JSVAL_NULL : JS_GetEmptyStringValue(cx);
        JS_free(cx, buf);
        return JS_TRUE;
    }

    /* Shrink the buffer to the real size. */
    tmp = (char *) JS_realloc(cx, buf, buflength);
    if (!tmp) {
        JS_free(cx, buf);
        return JS_FALSE;
    }

    buf = tmp;

    /*
     * Turn buf into a JSString. Note that buflength includes the trailing null
     * character.
     */
    str = JS_NewStringCopyN(cx, buf, sawNewline ? buflength - 1 : buflength);
    JS_free(cx, buf);
    if (!str)
        return JS_FALSE;

    *vp = STRING_TO_JSVAL(str);
    return JS_TRUE;
}

static JSBool
PutStr(JSContext *cx, uintN argc, jsval *vp)
{
    jsval *argv;
    JSString *str;
    char *bytes;

    if (argc != 0) {
        argv = JS_ARGV(cx, vp);
        str = JS_ValueToString(cx, argv[0]);
        if (!str)
            return JS_FALSE;
        bytes = JS_EncodeString(cx, str);
        if (!bytes)
            return JS_FALSE;
        cout << string(bytes);
        cout.flush();
        JS_free(cx, bytes);
    }

    JS_SET_RVAL(cx, vp, JSVAL_VOID);
    return JS_TRUE;
}

static JSBool
Now(JSContext *cx, uintN argc, jsval *vp)
{
    jsdouble now = PRMJ_Now() / double(PRMJ_USEC_PER_MSEC);
    JS_SET_RVAL(cx, vp, DOUBLE_TO_JSVAL(now));
    return true;
}

static JSBool
AssertJit(JSContext *cx, uintN argc, jsval *vp)
{
#ifdef JS_METHODJIT
    if (JS_GetOptions(cx) & JSOPTION_METHODJIT) {
        /*
         * :XXX: Ignore calls to this native when inference is enabled,
         * with METHODJIT_ALWAYS recompilation can happen and discard the
         * script's jitcode.
         */
        if (!cx->typeInferenceEnabled() &&
            !cx->fp()->script()->getJIT(cx->fp()->isConstructing())) {
            JS_ReportErrorNumber(cx, my_GetErrorMessage, NULL, JSSMSG_ASSERT_JIT_FAILED);
            return JS_FALSE;
        }
    }
#endif

    JS_SET_RVAL(cx, vp, JSVAL_VOID);
    return JS_TRUE;
}

static JSBool
GCParameter(JSContext *cx, uintN argc, jsval *vp)
{
    static const struct {
        const char      *name;
        JSGCParamKey    param;
    } paramMap[] = {
        {"maxBytes",            JSGC_MAX_BYTES },
        {"maxMallocBytes",      JSGC_MAX_MALLOC_BYTES},
        {"gcStackpoolLifespan", JSGC_STACKPOOL_LIFESPAN},
        {"gcBytes",             JSGC_BYTES},
        {"gcNumber",            JSGC_NUMBER},
    };

    JSString *str;
    if (argc == 0) {
        str = JS_ValueToString(cx, JSVAL_VOID);
        JS_ASSERT(str);
    } else {
        str = JS_ValueToString(cx, vp[2]);
        if (!str)
            return JS_FALSE;
        vp[2] = STRING_TO_JSVAL(str);
    }

    JSFlatString *flatStr = JS_FlattenString(cx, str);
    if (!flatStr)
        return JS_FALSE;

    size_t paramIndex = 0;
    for (;; paramIndex++) {
        if (paramIndex == JS_ARRAY_LENGTH(paramMap)) {
            JS_ReportError(cx,
                           "the first argument argument must be maxBytes, "
                           "maxMallocBytes, gcStackpoolLifespan, gcBytes or "
                           "gcNumber");
            return JS_FALSE;
        }
        if (JS_FlatStringEqualsAscii(flatStr, paramMap[paramIndex].name))
            break;
    }
    JSGCParamKey param = paramMap[paramIndex].param;

    if (argc == 1) {
        uint32 value = JS_GetGCParameter(cx->runtime, param);
        return JS_NewNumberValue(cx, value, &vp[0]);
    }

    if (param == JSGC_NUMBER ||
        param == JSGC_BYTES) {
        JS_ReportError(cx, "Attempt to change read-only parameter %s",
                       paramMap[paramIndex].name);
        return JS_FALSE;
    }

    uint32 value;
    if (!JS_ValueToECMAUint32(cx, vp[3], &value)) {
        JS_ReportError(cx,
                       "the second argument must be convertable to uint32 "
                       "with non-zero value");
        return JS_FALSE;
    }
    JS_SetGCParameter(cx->runtime, param, value);
    *vp = JSVAL_VOID;
    return JS_TRUE;
}

typedef struct JSCountHeapNode JSCountHeapNode;

struct JSCountHeapNode {
    void                *thing;
    JSGCTraceKind       kind;
    JSCountHeapNode     *next;
};

typedef struct JSCountHeapTracer {
    JSTracer            base;
    JSDHashTable        visited;
    JSBool              ok;
    JSCountHeapNode     *traceList;
    JSCountHeapNode     *recycleList;
} JSCountHeapTracer;

static void
CountHeapNotify(JSTracer *trc, void *thing, JSGCTraceKind kind)
{
    JSCountHeapTracer *countTracer;
    JSDHashEntryStub *entry;
    JSCountHeapNode *node;

    JS_ASSERT(trc->callback == CountHeapNotify);
    countTracer = (JSCountHeapTracer *)trc;
    if (!countTracer->ok)
        return;

    entry = (JSDHashEntryStub *)
            JS_DHashTableOperate(&countTracer->visited, thing, JS_DHASH_ADD);
    if (!entry) {
        JS_ReportOutOfMemory(trc->context);
        countTracer->ok = JS_FALSE;
        return;
    }
    if (entry->key)
        return;
    entry->key = thing;

    node = countTracer->recycleList;
    if (node) {
        countTracer->recycleList = node->next;
    } else {
        node = (JSCountHeapNode *) JS_malloc(trc->context, sizeof *node);
        if (!node) {
            countTracer->ok = JS_FALSE;
            return;
        }
    }
    node->thing = thing;
    node->kind = kind;
    node->next = countTracer->traceList;
    countTracer->traceList = node;
}

static JSBool
CountHeap(JSContext *cx, uintN argc, jsval *vp)
{
    void* startThing;
    JSGCTraceKind startTraceKind;
    jsval v;
    int32 traceKind, i;
    JSString *str;
    JSCountHeapTracer countTracer;
    JSCountHeapNode *node;
    size_t counter;

    static const struct {
        const char       *name;
        int32             kind;
    } traceKindNames[] = {
        { "all",        -1                  },
        { "object",     JSTRACE_OBJECT      },
        { "string",     JSTRACE_STRING      },
#if JS_HAS_XML_SUPPORT
        { "xml",        JSTRACE_XML         },
#endif
    };

    startThing = NULL;
    startTraceKind = JSTRACE_OBJECT;
    if (argc > 0) {
        v = JS_ARGV(cx, vp)[0];
        if (JSVAL_IS_TRACEABLE(v)) {
            startThing = JSVAL_TO_TRACEABLE(v);
            startTraceKind = JSVAL_TRACE_KIND(v);
        } else if (!JSVAL_IS_NULL(v)) {
            JS_ReportError(cx,
                           "the first argument is not null or a heap-allocated "
                           "thing");
            return JS_FALSE;
        }
    }

    traceKind = -1;
    if (argc > 1) {
        str = JS_ValueToString(cx, JS_ARGV(cx, vp)[1]);
        if (!str)
            return JS_FALSE;
        JSFlatString *flatStr = JS_FlattenString(cx, str);
        if (!flatStr)
            return JS_FALSE;
        for (i = 0; ;) {
            if (JS_FlatStringEqualsAscii(flatStr, traceKindNames[i].name)) {
                traceKind = traceKindNames[i].kind;
                break;
            }
            if (++i == JS_ARRAY_LENGTH(traceKindNames)) {
                JSAutoByteString bytes(cx, str);
                if (!!bytes)
                    JS_ReportError(cx, "trace kind name '%s' is unknown", bytes.ptr());
                return JS_FALSE;
            }
        }
    }

    JS_TRACER_INIT(&countTracer.base, cx, CountHeapNotify);
    if (!JS_DHashTableInit(&countTracer.visited, JS_DHashGetStubOps(),
                           NULL, sizeof(JSDHashEntryStub),
                           JS_DHASH_DEFAULT_CAPACITY(100))) {
        JS_ReportOutOfMemory(cx);
        return JS_FALSE;
    }
    countTracer.ok = JS_TRUE;
    countTracer.traceList = NULL;
    countTracer.recycleList = NULL;

    if (!startThing) {
        JS_TraceRuntime(&countTracer.base);
    } else {
        JS_SET_TRACING_NAME(&countTracer.base, "root");
        JS_CallTracer(&countTracer.base, startThing, startTraceKind);
    }

    counter = 0;
    while ((node = countTracer.traceList) != NULL) {
        if (traceKind == -1 || node->kind == traceKind)
            counter++;
        countTracer.traceList = node->next;
        node->next = countTracer.recycleList;
        countTracer.recycleList = node;
        JS_TraceChildren(&countTracer.base, node->thing, node->kind);
    }
    while ((node = countTracer.recycleList) != NULL) {
        countTracer.recycleList = node->next;
        JS_free(cx, node);
    }
    JS_DHashTableFinish(&countTracer.visited);

    return countTracer.ok && JS_NewNumberValue(cx, (jsdouble) counter, vp);
}

static jsrefcount finalizeCount = 0;

static void
finalize_counter_finalize(JSContext *cx, JSObject *obj)
{
    JS_ATOMIC_INCREMENT(&finalizeCount);
}

static JSClass FinalizeCounterClass = {
    "FinalizeCounter", JSCLASS_IS_ANONYMOUS,
    JS_PropertyStub,       /* addProperty */
    JS_PropertyStub,       /* delProperty */
    JS_PropertyStub,       /* getProperty */
    JS_StrictPropertyStub, /* setProperty */
    JS_EnumerateStub,
    JS_ResolveStub,
    JS_ConvertStub,
    finalize_counter_finalize
};

static JSBool
MakeFinalizeObserver(JSContext *cx, uintN argc, jsval *vp)
{
    JSObject *obj = JS_NewObjectWithGivenProto(cx, &FinalizeCounterClass, NULL,
                                               JS_GetGlobalObject(cx));
    if (!obj)
        return false;
    *vp = OBJECT_TO_JSVAL(obj);
    return true;
}

static JSBool
FinalizeCount(JSContext *cx, uintN argc, jsval *vp)
{
    *vp = INT_TO_JSVAL(finalizeCount);
    return true;
}

static JSBool
GCZeal(JSContext *cx, uintN argc, jsval *vp)
{
    uint32 zeal, frequency = JS_DEFAULT_ZEAL_FREQ;
    JSBool compartment = JS_FALSE;

    if (argc > 3) {
        JS_ReportErrorNumber(cx, my_GetErrorMessage, NULL, JSSMSG_TOO_MANY_ARGS, "gczeal");
        return JS_FALSE;
    }
    if (!JS_ValueToECMAUint32(cx, argc < 1 ? JSVAL_VOID : vp[2], &zeal))
        return JS_FALSE;
    if (argc >= 2)
        if (!JS_ValueToECMAUint32(cx, vp[3], &frequency))
            return JS_FALSE;
    if (argc >= 3)
        compartment = js_ValueToBoolean(Valueify(vp[3]));

    JS_SetGCZeal(cx, (uint8)zeal, frequency, compartment);
    *vp = JSVAL_VOID;
    return JS_TRUE;
}

static JSBool
ScheduleGC(JSContext *cx, uintN argc, jsval *vp)
{
    uint32 count;
    bool compartment = false;

    if (argc != 1 && argc != 2) {
        JS_ReportErrorNumber(cx, my_GetErrorMessage, NULL,
                             (argc < 1)
                             ? JSSMSG_NOT_ENOUGH_ARGS
                             : JSSMSG_TOO_MANY_ARGS,
                             "schedulegc");
        return JS_FALSE;
    }
    if (!JS_ValueToECMAUint32(cx, vp[2], &count))
        return JS_FALSE;
    if (argc == 2)
        compartment = js_ValueToBoolean(Valueify(vp[3]));

    JS_ScheduleGC(cx, count, compartment);
    *vp = JSVAL_VOID;
    return JS_TRUE;
}

static JSClass env_class = {
    "environment", JSCLASS_HAS_PRIVATE | JSCLASS_NEW_RESOLVE,
    JS_PropertyStub,  JS_PropertyStub,
    JS_PropertyStub,  env_setProperty,
    env_enumerate, (JSResolveOp) env_resolve,
    JS_ConvertStub,   NULL,
    JSCLASS_NO_OPTIONAL_MEMBERS
};

void reportError(JSContext *ctx, const char *message, JSErrorReport *report)
{
    fprintf(stderr, "%s:%u:%s\n",
            report->filename ? report->filename : "<no filename>",
            (unsigned int)report->lineno,
            message);
}

enum CompartmentKind { SAME_COMPARTMENT, NEW_COMPARTMENT };

static JSBool its_noisy;    /* whether to be noisy when finalizing it */
static JSBool its_enum_fail;/* whether to fail when enumerating it */

static JSBool
its_addProperty(JSContext *cx, JSObject *obj, jsid id, jsval *vp)
{
    if (!its_noisy)
        return JS_TRUE;

    IdStringifier idString(cx, id);
    printf("adding its property %s,", idString.getBytes());
    ToString valueString(cx, *vp);
    printf(" initial value %s\n", valueString.getBytes());
    return JS_TRUE;
}

static JSBool
its_delProperty(JSContext *cx, JSObject *obj, jsid id, jsval *vp)
{
    if (!its_noisy)
        return JS_TRUE;

    IdStringifier idString(cx, id);
    printf("deleting its property %s,", idString.getBytes());
    ToString valueString(cx, *vp);
    printf(" initial value %s\n", valueString.getBytes());
    return JS_TRUE;
}

static JSBool
its_getProperty(JSContext *cx, JSObject *obj, jsid id, jsval *vp)
{
    if (!its_noisy)
        return JS_TRUE;

    IdStringifier idString(cx, id);
    printf("getting its property %s,", idString.getBytes());
    ToString valueString(cx, *vp);
    printf(" initial value %s\n", valueString.getBytes());
    return JS_TRUE;
}

static JSBool
its_setProperty(JSContext *cx, JSObject *obj, jsid id, JSBool strict, jsval *vp)
{
    IdStringifier idString(cx, id);
    if (its_noisy) {
        printf("setting its property %s,", idString.getBytes());
        ToString valueString(cx, *vp);
        printf(" new value %s\n", valueString.getBytes());
    }

    if (!JSID_IS_ATOM(id))
        return JS_TRUE;

    if (!strcmp(idString.getBytes(), "noisy"))
        JS_ValueToBoolean(cx, *vp, &its_noisy);
    else if (!strcmp(idString.getBytes(), "enum_fail"))
        JS_ValueToBoolean(cx, *vp, &its_enum_fail);

    return JS_TRUE;
}

/*
 * Its enumerator, implemented using the "new" enumerate API,
 * see class flags.
 */
static JSBool
its_enumerate(JSContext *cx, JSObject *obj, JSIterateOp enum_op,
              jsval *statep, jsid *idp)
{
    JSObject *iterator;

    switch (enum_op) {
      case JSENUMERATE_INIT:
      case JSENUMERATE_INIT_ALL:
        if (its_noisy)
            printf("enumerate its properties\n");

        iterator = JS_NewPropertyIterator(cx, obj);
        if (!iterator)
            return JS_FALSE;

        *statep = OBJECT_TO_JSVAL(iterator);
        if (idp)
            *idp = INT_TO_JSID(0);
        break;

      case JSENUMERATE_NEXT:
        if (its_enum_fail) {
            JS_ReportError(cx, "its enumeration failed");
            return JS_FALSE;
        }

        iterator = (JSObject *) JSVAL_TO_OBJECT(*statep);
        if (!JS_NextProperty(cx, iterator, idp))
            return JS_FALSE;

        if (!JSID_IS_VOID(*idp))
            break;
        /* Fall through. */

      case JSENUMERATE_DESTROY:
        /* Allow our iterator object to be GC'd. */
        *statep = JSVAL_NULL;
        break;
    }

    return JS_TRUE;
}

static JSBool
its_resolve(JSContext *cx, JSObject *obj, jsid id, uintN flags,
            JSObject **objp)
{
    if (its_noisy) {
        IdStringifier idString(cx, id);
        printf("resolving its property %s, flags {%s,%s,%s}\n",
               idString.getBytes(),
               (flags & JSRESOLVE_QUALIFIED) ? "qualified" : "",
               (flags & JSRESOLVE_ASSIGNING) ? "assigning" : "",
               (flags & JSRESOLVE_DETECTING) ? "detecting" : "");
    }
    return JS_TRUE;
}

static JSBool
its_convert(JSContext *cx, JSObject *obj, JSType type, jsval *vp)
{
    if (its_noisy)
        printf("converting it to %s type\n", JS_GetTypeName(cx, type));
    return JS_ConvertStub(cx, obj, type, vp);
}

static void
its_finalize(JSContext *cx, JSObject *obj)
{
    jsval *rootedVal;
    if (its_noisy)
        printf("finalizing it\n");
    rootedVal = (jsval *) JS_GetPrivate(cx, obj);
    if (rootedVal) {
      JS_RemoveValueRoot(cx, rootedVal);
      JS_SetPrivate(cx, obj, NULL);
      delete rootedVal;
    }
}

static JSClass its_class = {
    "It", JSCLASS_NEW_RESOLVE | JSCLASS_NEW_ENUMERATE | JSCLASS_HAS_PRIVATE,
    its_addProperty,  its_delProperty,  its_getProperty,  its_setProperty,
    (JSEnumerateOp)its_enumerate, (JSResolveOp)its_resolve,
    its_convert,      its_finalize,
    JSCLASS_NO_OPTIONAL_MEMBERS
};

static JSObject *
NewGlobalObject(JSContext *cx, CompartmentKind compartment);

JSBool
NewGlobal(JSContext *cx, uintN argc, jsval *vp)
{
    if (argc != 1 || !JSVAL_IS_STRING(JS_ARGV(cx, vp)[0])) {
        JS_ReportErrorNumber(cx, my_GetErrorMessage, NULL, JSSMSG_INVALID_ARGS, "newGlobal");
        return false;
    }

    JSString *str = JSVAL_TO_STRING(JS_ARGV(cx, vp)[0]);

    JSBool equalSame = JS_FALSE, equalNew = JS_FALSE;
    if (!JS_StringEqualsAscii(cx, str, "same-compartment", &equalSame) ||
        !JS_StringEqualsAscii(cx, str, "new-compartment", &equalNew)) {
        return false;
    }

    if (!equalSame && !equalNew) {
        JS_ReportErrorNumber(cx, my_GetErrorMessage, NULL, JSSMSG_INVALID_ARGS, "newGlobal");
        return false;
    }

    JSObject *global = NewGlobalObject(cx, equalSame ? SAME_COMPARTMENT : NEW_COMPARTMENT);
    if (!global)
        return false;

    JS_SET_RVAL(cx, vp, OBJECT_TO_JSVAL(global));
    return true;
}

enum its_tinyid {
    ITS_COLOR, ITS_HEIGHT, ITS_WIDTH, ITS_FUNNY, ITS_ARRAY, ITS_RDONLY,
    ITS_CUSTOM, ITS_CUSTOMRDONLY
};

static JSBool
its_getter(JSContext *cx, JSObject *obj, jsid id, jsval *vp)
{
  jsval *val = (jsval *) JS_GetPrivate(cx, obj);
  *vp = val ? *val : JSVAL_VOID;
  return JS_TRUE;
}

static JSBool
its_setter(JSContext *cx, JSObject *obj, jsid id, JSBool strict, jsval *vp)
{
  jsval *val = (jsval *) JS_GetPrivate(cx, obj);
  if (val) {
      *val = *vp;
      return JS_TRUE;
  }

  val = new jsval;
  if (!val) {
      JS_ReportOutOfMemory(cx);
      return JS_FALSE;
  }

  if (!JS_AddValueRoot(cx, val)) {
      delete val;
      return JS_FALSE;
  }

  if (!JS_SetPrivate(cx, obj, (void*)val)) {
      JS_RemoveValueRoot(cx, val);
      delete val;
      return JS_FALSE;
  }

  *val = *vp;
  return JS_TRUE;
}

static JSBool
its_bindMethod(JSContext *cx, uintN argc, jsval *vp)
{
    JSString *name;
    JSObject *method;

    JSObject *thisobj = JS_THIS_OBJECT(cx, vp);

    if (!JS_ConvertArguments(cx, argc, JS_ARGV(cx, vp), "So", &name, &method))
        return JS_FALSE;

    *vp = OBJECT_TO_JSVAL(method);

    if (JS_TypeOfValue(cx, *vp) != JSTYPE_FUNCTION) {
        JSAutoByteString nameBytes(cx, name);
        if (!!nameBytes) {
            JSString *valstr = JS_ValueToString(cx, *vp);
            if (valstr) {
                JSAutoByteString valBytes(cx, valstr);
                if (!!valBytes) {
                    JS_ReportError(cx, "can't bind method %s to non-callable object %s",
                                   nameBytes.ptr(), valBytes.ptr());
                }
            }
        }
        return JS_FALSE;
    }

    if (method->getFunctionPrivate()->isInterpreted() &&
        method->getFunctionPrivate()->script()->compileAndGo) {
        /* Can't reparent compileAndGo scripts. */
        JSAutoByteString nameBytes(cx, name);
        if (!!nameBytes)
            JS_ReportError(cx, "can't bind method %s to compileAndGo script", nameBytes.ptr());
        return JS_FALSE;
    }

    jsid id;
    if (!JS_ValueToId(cx, STRING_TO_JSVAL(name), &id))
        return JS_FALSE;

    if (!JS_DefinePropertyById(cx, thisobj, id, *vp, NULL, NULL, JSPROP_ENUMERATE))
        return JS_FALSE;

    return JS_SetParent(cx, method, thisobj);
}

static JSFunctionSpec its_methods[] = {
    {"bindMethod",      its_bindMethod, 2,0},
    {NULL,NULL,0,0}
};

static JSPropertySpec its_props[] = {
    {"color",           ITS_COLOR,      JSPROP_ENUMERATE,       NULL, NULL},
    {"height",          ITS_HEIGHT,     JSPROP_ENUMERATE,       NULL, NULL},
    {"width",           ITS_WIDTH,      JSPROP_ENUMERATE,       NULL, NULL},
    {"funny",           ITS_FUNNY,      JSPROP_ENUMERATE,       NULL, NULL},
    {"array",           ITS_ARRAY,      JSPROP_ENUMERATE,       NULL, NULL},
    {"rdonly",          ITS_RDONLY,     JSPROP_READONLY,        NULL, NULL},
    {"custom",          ITS_CUSTOM,     JSPROP_ENUMERATE,
                        its_getter,     its_setter},
    {"customRdOnly",    ITS_CUSTOMRDONLY, JSPROP_ENUMERATE | JSPROP_READONLY,
                        its_getter,     its_setter},
    {NULL,0,0,NULL,NULL}
};

JSBool
Serialize(JSContext *cx, uintN argc, jsval *vp)
{
    jsval v = argc > 0 ? JS_ARGV(cx, vp)[0] : JSVAL_VOID;
    uint64 *datap;
    size_t nbytes;
    if (!JS_WriteStructuredClone(cx, v, &datap, &nbytes, NULL, NULL))
        return false;

    JSObject *arrayobj = js_CreateTypedArray(cx, TypedArray::TYPE_UINT8, nbytes);
    if (!arrayobj) {
        JS_free(cx, datap);
        return false;
    }
    JSObject *array = TypedArray::getTypedArray(arrayobj);
    JS_ASSERT((uintptr_t(TypedArray::getDataOffset(array)) & 7) == 0);
    memcpy(TypedArray::getDataOffset(array), datap, nbytes);
    JS_free(cx, datap);
    JS_SET_RVAL(cx, vp, OBJECT_TO_JSVAL(arrayobj));
    return true;
}

static JSFunctionSpec functions[] = {
    JS_FN("version",        Version,        0,0),
    JS_FN("revertVersion",  RevertVersion,  0,0),
    JS_FN("options",        Options,        0,0),
    JS_FN("load",           Load,           1,0),
    JS_FN("evaluate",       Evaluate,       1,0),
    JS_FN("run",            Run,            1,0),
    JS_FN("readline",       ReadLine,       0,0),
    JS_FN("print",          Print,          0,0),
    JS_FN("putstr",         PutStr,         0,0),
    JS_FN("dateNow",        Now,            0,0),
    JS_FN("assertEq",       AssertEq,       2,0),
    JS_FN("assertJit",      AssertJit,      0,0),
    JS_FN("gc",             ::GC,           0,0),
    JS_FN("gcparam",        GCParameter,    2,0),
    JS_FN("countHeap",      CountHeap,      0,0),
    JS_FN("makeFinalizeObserver", MakeFinalizeObserver, 0,0),
    JS_FN("finalizeCount",  FinalizeCount,  0,0),
    JS_FN("gczeal",         GCZeal,         2,0),
    JS_FN("schedulegc",     ScheduleGC,     1,0),
    JS_FN("newGlobal",      NewGlobal,      1,0),
    JS_FN("serialize",      Serialize,      1,0),

    JS_FS_END
};

static JSObject *
NewGlobalObject(JSContext *cx, CompartmentKind compartment)
{
    JSObject *glob = (compartment == NEW_COMPARTMENT)
                     ? JS_NewCompartmentAndGlobalObject(cx, &global_class, NULL)
                     : JS_NewGlobalObject(cx, &global_class);
    if (!glob)
        return NULL;

    {
        JSAutoEnterCompartment ac;
        if (!ac.enter(cx, glob))
            return NULL;

#ifndef LAZY_STANDARD_CLASSES
        if (!JS_InitStandardClasses(cx, glob))
            return NULL;
#endif

#ifdef JS_HAS_CTYPES
        if (!JS_InitCTypesClass(cx, glob))
            return NULL;
#endif
        if (!JS_InitReflect(cx, glob))
            return NULL;
        if (!JS_DefineDebuggerObject(cx, glob))
            return NULL;
        if (!JS::RegisterPerfMeasurement(cx, glob))
            return NULL;
        if (!JS_DefineFunctions(cx, glob, functions) ||
            !JS_DefineProfilingFunctions(cx, glob)) {
            return NULL;
        }

        JSObject *it = JS_DefineObject(cx, glob, "it", &its_class, NULL, 0);
        if (!it)
            return NULL;
        if (!JS_DefineProperties(cx, it, its_props))
            return NULL;
        if (!JS_DefineFunctions(cx, it, its_methods))
            return NULL;

        if (!JS_DefineProperty(cx, glob, "custom", JSVAL_VOID, its_getter,
                               its_setter, 0))
            return NULL;
        if (!JS_DefineProperty(cx, glob, "customRdOnly", JSVAL_VOID, its_getter,
                               its_setter, JSPROP_READONLY))
            return NULL;
    }

    if (compartment == NEW_COMPARTMENT && !JS_WrapObject(cx, &glob))
        return NULL;

    return glob;
}

struct JSShellContextData {
    volatile JSIntervalTime startTime;
};

static JSShellContextData *
NewContextData()
{
    JSShellContextData *data = (JSShellContextData *)
                               calloc(sizeof(JSShellContextData), 1);
    if (!data)
        return NULL;
    data->startTime = js_IntervalNow();
    return data;
}

static inline JSShellContextData *
GetContextData(JSContext *cx)
{
    JSShellContextData *data = (JSShellContextData *) JS_GetContextPrivate(cx);

    JS_ASSERT(data);
    return data;
}