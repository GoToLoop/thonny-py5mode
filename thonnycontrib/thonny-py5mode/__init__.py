'''thonny-py5mode frontend
interacts with py5mode backend (backend > py5_imported_mode_backend.py)'''

import pathlib, site, subprocess, sys, types, webbrowser

from os import path, environ as env
from typing import NamedTuple

from distutils.sysconfig import get_python_lib
from importlib import machinery, util
from tkinter.messagebox import showerror, showinfo

from thonny import get_runner, editors, running, token_utils
from thonny.common import InputSubmission
from thonny.languages import tr
from thonny.running import Runner
from thonny.shell import BaseShellText

from .about_plugin import add_about_py5mode_command
from .install_jdk import install_jdk, WORKBENCH

# Modified tkColorPicker (by j4321) to work with Thonny for MacOS:
# https://GitHub.com/tabreturn/thonny-py5mode-tkcolorpicker
# Now vendored on this very repo:
from .py5colorpicker.tkcolorpicker import modeless_colorpicker

_PY5_IMPORTED_MODE = 'run.py5_imported_mode'

_MENU = NamedTuple('Py5Menu', ( # define all fields as type str
    ('TOGGLE_PY5', str),
    ('P5_THEME', str),
    ('COLOR_PICKER', str),
    ('PY5_REF', str),
    ('PY5_PDF', str),
    ('SKETCH_DIR', str)))(*map(tr, ( # immediately invoked instantiation
        'Imported mode for py5',
        'Apply recommended py5 settings',
        'Color selector',
        'py5 reference',
        'py5 quick reference',
        'Show sketch folder')))
'''
NamedTuple containing UI translated labels for plugin py5mode related features:
- TOGGLE_PY5: Label for toggling py5 mode.
- P5_THEME: Label for applying recommended py5 settings.
- COLOR_PICKER: Label for the color selector tool.
- PY5_REF: Label for accessing the py5 reference.
- PY5_PDF: Label for viewing the py5 quick reference PDF.
- SKETCH_DIR: Label for showing the sketch folder.'''

_TITLE, _MSG = map(tr, ('py5 Conversion', 'Conversion complete'))

EXTS = 'py', 'py5', 'pyde'

_HTTP, _PY5_SITE, _REF = 'https://', 'py5Coding', '.org/reference/'
_OPEN_REF = _HTTP + _PY5_SITE + _REF

_GIT_RAW = _HTTP + 'raw.GitHubUserContent.com/'
_REF_PDF = _PY5_SITE + '/thonny-py5mode/main/assets/py5_quick_reference.pdf'
_OPEN_PDF = _GIT_RAW + _REF_PDF

def _open_ref(): webbrowser.open(_OPEN_REF)
def _open_pdf(): webbrowser.open(_OPEN_PDF)

_is_color_selector_open = False

def apply_recommended_py5_config() -> None:
    '''Apply some recommended settings for thonny py5 work'''

    WORKBENCH.set_option("view.ui_theme", "Kyanite UI")
    WORKBENCH.set_option("view.syntax_theme", "Kyanite Syntax")
    WORKBENCH.set_option("view.highlight_current_line", "True")
    WORKBENCH.set_option("view.locals_highlighting", "True")
    WORKBENCH.set_option("assistance.open_assistant_on_errors", "False")
    WORKBENCH.set_option("view.assistantview", False)
    WORKBENCH.hide_view("AssistantView")
    WORKBENCH.reload_themes()


def execute_imported_mode() -> None:
    '''Run imported mode script using py5_tools run_sketch'''

    current_editor = WORKBENCH.get_editor_notebook().get_current_editor()
    current_file = current_editor.get_filename()

    if current_file is None:
        # Thonny must 'save as' any new files, before it can run them:
        editors.Editor.save_file(current_editor)
        current_file = current_editor.get_filename()

    if current_file and current_file.split(".")[-1] in EXTS:
        # Save and run py5 imported mode:
        current_editor.save_file()
        user_packages = str(site.getusersitepackages())
        site_packages = str(site.getsitepackages()[0])
        plug_packages = util.find_spec("py5_tools").submodule_search_locations
        run_sketch_locations = [
            pathlib.Path(user_packages + "/py5_tools/tools/run_sketch.py"),
            pathlib.Path(site_packages + "/py5_tools/tools/run_sketch.py"),
            pathlib.Path(plug_packages[0] + "/tools/run_sketch.py"),
            pathlib.Path(get_python_lib() + "/py5_tools/tools/run_sketch.py"),
        ]

        for location in run_sketch_locations:
            # If location matches py5_tools path, use it:
            if location.is_file():
                run_sketch = location
                break

        # Set switch so Sketch will report window location:
        py5_switches = "--py5_options external"
        # Retrieve last display window location:
        py5_loc = WORKBENCH.get_option("run.py5_location")
        if py5_loc:
            # Add location switch to command line:
            py5_switches += " location=" + ",".join(map(str, py5_loc))

        # Run command to execute sketch:
        working_directory = path.dirname(current_file)
        cd_cmd_line = running.construct_cd_command(working_directory) + "\n"
        cmd_parts = ["%Run", str(run_sketch), current_file]
        exe_cmd_line = running.construct_cmd_line(cmd_parts) + " "
        exe_cmd_line += py5_switches + "\n"
        running.get_shell().submit_magic_command(cd_cmd_line + exe_cmd_line)


def patched_execute_current(self: Runner, command_name: str) -> None:
    '''Override run button behavior for py5 imported mode'''
    execute_imported_mode()


def patch_token_coloring() -> None:
    '''Add py5 keywords to syntax highlighting'''

    spec = util.find_spec("py5_tools")
    # Cannot use `dir(py5)` because of jvm check, hence direct loading:
    path = pathlib.Path(spec.submodule_search_locations[0]) / "reference.py"
    loader = machinery.SourceFileLoader("py5_tools_reference", str(path))
    module = types.ModuleType(loader.name)
    loader.exec_module(module)
    # Add keywords to thonny builtin list:
    patched_builtinlist = token_utils._builtinlist + module.PY5_ALL_STR
    matches = token_utils.matches_any("builtin", patched_builtinlist)
    patched_BUILTIN = r'([^.\'"\\#]\b|^)' + (matches + r"\b")
    token_utils.BUILTIN = patched_BUILTIN


def set_py5_imported_mode() -> None:
    '''Set imported mode variable in thonny configuration.ini file'''

    if WORKBENCH.in_simple_mode():
        env["PY5_IMPORTED_MODE"] = "auto"
    else:
        p_i_m = str(WORKBENCH.get_option(_PY5_IMPORTED_MODE))
        env["PY5_IMPORTED_MODE"] = p_i_m

        # Switch on/off py5 run button behavior:
        if WORKBENCH.get_option(_PY5_IMPORTED_MODE):
            Runner._original_execute_current = Runner.execute_current
            Runner.execute_current = patched_execute_current
            # Must restart backend for py5 autocompletion upon installing JDK:
            try:
                get_runner().restart_backend(False)
            except AttributeError:
                pass
        else:
            # Patched method non-existant when imported mode active at launch:
            try:
                Runner.execute_current = Runner._original_execute_current
                # This line disable py5 autocompletion in this instance:
                get_runner().restart_backend(False)
            except AttributeError:
                pass


def toggle_py5_imported_mode() -> None:
    '''Toggle py5 imported mode settings'''

    var = WORKBENCH.get_variable(_PY5_IMPORTED_MODE)
    var.set(not var.get())
    install_jdk()
    set_py5_imported_mode()


def color_selector() -> None:
    '''Open tkinter color selector'''

    global _is_color_selector_open

    if not _is_color_selector_open: # if one is not already open...
        _is_color_selector_open = True
        modeless_colorpicker(title=_MENU.COLOR_PICKER)
        _is_color_selector_open = False


def convert_code(translator) -> None:
    '''Function to handle different py5_tools conversions'''

    current_editor = WORKBENCH.get_editor_notebook().get_current_editor()
    current_file = current_editor.get_filename()

    if current_file is None:
        # Save unsaved file before attempting to convert it:
        editors.Editor.save_file(current_editor)
        current_file = current_editor.get_filename()

    if current_file and current_file.split(".")[-1] in EXTS:
        # Save and run perform conversion:
        current_editor.save_file()
        translator.translate_file(current_file, current_file)
        current_editor._load_file(current_file, keep_undo=True)
        showinfo(_TITLE, _MSG, parent=WORKBENCH)


def show_sketch_folder() -> None:
    '''Open the enclosing folder of the current file'''

    current_editor = WORKBENCH.get_editor_notebook().get_current_editor()
    # Check if the editor is empty/blank:
    try:
        filename = current_editor.get_filename()
    except AttributeError:
        showerror("Editor is empty", "Do you have a file open in the editor?")
        return
    # Check if the file isn't an <untitled> (yet to be saved) file:
    try:
        path_dir = path.dirname(filename)
    except TypeError:
        showerror("File not found", "Have you saved your file somewhere yet?")
        return
    # Open file manager for mac/linux/windows:
    if sys.platform == "darwin":
        subprocess.Popen(["open", path_dir])
    elif sys.platform == "linux":
        subprocess.Popen(["xdg-open", path_dir])
    else:
        subprocess.Popen(["explorer", path_dir])


def patched_handle_program_output(self: BaseShellText, msg: InputSubmission):
    '''Catch display window movements and write coords. to the config file'''

    # If not a window move event, forward the message to the original function,
    # so it prints the rest of the shell output as usual:
    if not msg.data.startswith('__MOVE__'):
        return getattr(self, 'original_handle_program_output')(msg)

    py5_loc = msg.data[9:-1].split()

    # Write display window location to config file:
    if len(py5_loc) == 2:
        py5_loc = py5_loc[0] + ',' + py5_loc[1]
        WORKBENCH.set_option('run.py5_location', py5_loc)


def load_plugin() -> None:
    '''Thonny's plugin callback'''

    WORKBENCH.set_default(_PY5_IMPORTED_MODE, False)

    cmd = WORKBENCH.add_command

    cmd('toggle_py5_imported_mode', 'py5', _MENU.TOGGLE_PY5,
        toggle_py5_imported_mode, flag_name=_PY5_IMPORTED_MODE, group=10)

    cmd('apply_recommended_py5_config', 'py5', _MENU.P5_THEME,
        apply_recommended_py5_config, group=20)

    cmd('py5_color_selector', 'py5', _MENU.COLOR_PICKER,
        color_selector, group=30, default_sequence='<Alt-c>')

    cmd('py5_reference', 'py5', _MENU.PY5_REF, _open_ref, group=30)

    cmd('py5_quickreference', 'py5', _MENU.PY5_PDF, _open_pdf, group=30)

    cmd('open_folder', 'py5', _MENU.SKETCH_DIR, show_sketch_folder, group=40)

    add_about_py5mode_command(50)
    patch_token_coloring()
    set_py5_imported_mode()

    # Note that _handle_program_output() is not a public API!
    # May need to treat different Thonny versions differently:
    h_p_o = BaseShellText._handle_program_output
    setattr(BaseShellText, 'original_handle_program_output', h_p_o)
    BaseShellText._handle_program_output = patched_handle_program_output
