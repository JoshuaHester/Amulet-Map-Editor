import wx
from wx import glcanvas
from OpenGL.GL import *
import sys
import os
from typing import TYPE_CHECKING, Optional

from amulet.api.selection import Selection, SubSelectionBox
from amulet.api.structure import Structure
import minecraft_model_reader

from amulet_map_editor.plugins.programs import BaseWorldProgram
from amulet_map_editor.amulet_wx.simple import SimplePanel, SimpleChoiceAny
from amulet_map_editor.opengl.mesh.world_renderer.world import RenderWorld
from amulet_map_editor.plugins import operations
from amulet_map_editor import log

if TYPE_CHECKING:
    from amulet.api.world import World


key_map = {
    'up': wx.WXK_SPACE,
    'down': wx.WXK_SHIFT,
    'forwards': 87,
    'backwards': 83,
    'left': 65,
    'right': 68,

    'look_left': 74,
    'look_right': 76,
    'look_up': 73,
    'look_down': 75,
}


class World3dCanvas(glcanvas.GLCanvas):
    def __init__(self, world_panel: 'World3DPanel', world: 'World'):
        self._keys_pressed = set()
        super().__init__(world_panel, -1, size=world_panel.GetClientSize())
        self._context = glcanvas.GLContext(self)
        self.SetCurrent(self._context)
        glClearColor(0.5, 0.66, 1.0, 1.0)
        glEnable(GL_DEPTH_TEST)
        glEnable(GL_CULL_FACE)
        glDepthFunc(GL_LEQUAL)
        glEnable(GL_BLEND)
        glBlendFunc(GL_SRC_ALPHA, GL_ONE_MINUS_SRC_ALPHA)

        os.makedirs('resource_packs', exist_ok=True)
        if not os.path.isfile('resource_packs/readme.txt'):
            with open('resource_packs/readme.txt', 'w') as f:
                f.write('Put the Java resource pack you want loaded in here.')

        resource_packs = [minecraft_model_reader.java_vanilla_latest] + \
                         [minecraft_model_reader.JavaRP(rp) for rp in os.listdir('resource_packs') if os.path.isdir(rp)] + \
                         [minecraft_model_reader.java_vanilla_fix, minecraft_model_reader.JavaRP(os.path.join(os.path.dirname(__file__), 'amulet_resource_pack'))]
        resource_pack = minecraft_model_reader.JavaRPHandler(resource_packs)

        self._render_world = RenderWorld(world, resource_pack)

        self._draw_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._on_draw, self._draw_timer)

        self._input_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._process_inputs, self._input_timer)

        self._gc_timer = wx.Timer(self)
        self.Bind(wx.EVT_TIMER, self._gc, self._gc_timer)

        world_panel.Bind(wx.EVT_SIZE, self._on_resize)

        self.Bind(wx.EVT_KEY_DOWN, self._on_key_press)
        self.Bind(wx.EVT_KEY_UP, self._on_key_release)
        self.Bind(wx.EVT_MOUSEWHEEL, self._mouse_wheel)
        self.Bind(wx.EVT_KILL_FOCUS, self._on_loss_focus)

        self._mouse_x = 0
        self._mouse_y = 0
        self._last_mouse_x = 0
        self._last_mouse_y = 0
        self._mouse_lock = False
        self.Bind(wx.EVT_MIDDLE_UP, self._toggle_mouse_lock)
        self.Bind(wx.EVT_LEFT_UP, self._box_click)
        self.Bind(wx.EVT_RIGHT_UP, self._toggle_selection_mode)
        self.Bind(wx.EVT_MOTION, self._on_mouse_motion)

    def enable(self):
        self._render_world.enable()
        self._draw_timer.Start(33)
        self._input_timer.Start(33)
        self._gc_timer.Start(10000)

    def disable(self):
        self._draw_timer.Stop()
        self._input_timer.Stop()
        self._gc_timer.Stop()
        self._render_world.disable()

    def close(self):
        self._render_world.close()

    def is_closeable(self):
        return self._render_world.is_closeable()

    def _mouse_wheel(self, evt):
        self._render_world.camera_move_speed += 0.2 * evt.GetWheelRotation() / evt.GetWheelDelta()
        if self._render_world.camera_move_speed < 0.1:
            self._render_world.camera_move_speed = 0.1
        evt.Skip()

    def _process_inputs(self, evt):
        forward, up, right, pitch, yaw = 0, 0, 0, 0, 0
        if key_map['up'] in self._keys_pressed:
            up += 1
        if key_map['down'] in self._keys_pressed:
            up -= 1
        if key_map['forwards'] in self._keys_pressed:
            forward += 1
        if key_map['backwards'] in self._keys_pressed:
            forward -= 1
        if key_map['left'] in self._keys_pressed:
            right -= 1
        if key_map['right'] in self._keys_pressed:
            right += 1

        if self._mouse_lock:
            pitch = (self._mouse_y - self._last_mouse_y) * 0.07
            yaw = (self._mouse_x - self._last_mouse_x) * 0.07
            self._mouse_x, self._mouse_y = self._last_mouse_x, self._last_mouse_y = self.GetSize()[0]/2, self.GetSize()[1]/2
            self.WarpPointer(self._last_mouse_x, self._last_mouse_y)
        else:
            pitch = 0
            yaw = 0
        self._render_world.move_camera(forward, up, right, pitch, yaw)
        evt.Skip()

    def _toggle_mouse_lock(self, evt):
        self.SetFocus()
        if self._mouse_lock:
            self._release_mouse()
        else:
            self.CaptureMouse()
            wx.SetCursor(wx.Cursor(wx.CURSOR_BLANK))
            self._mouse_x, self._mouse_y = self._last_mouse_x, self._last_mouse_y = evt.GetPosition()
            self._mouse_lock = True

    def _box_click(self, evt):
        self._render_world.left_click()
        evt.Skip()

    def _toggle_selection_mode(self, evt):
        self._render_world.right_click()
        evt.Skip()

    def _release_mouse(self):
        wx.SetCursor(wx.NullCursor)
        try:
            self.ReleaseMouse()
        except:
            pass
        self._mouse_lock = False

    def _on_mouse_motion(self, evt):
        if self._mouse_lock:
            self._mouse_x, self._mouse_y = evt.GetPosition()

    def _on_key_release(self, event):
        key = event.GetUnicodeKey()
        if key == wx.WXK_NONE:
            key = event.GetKeyCode()
        if key in self._keys_pressed:
            self._keys_pressed.remove(key)

    def _on_key_press(self, event):
        key = event.GetUnicodeKey()
        if key == wx.WXK_NONE:
            key = event.GetKeyCode()
        self._keys_pressed.add(key)
        if key == wx.WXK_ESCAPE:
            self._escape()

    def _on_loss_focus(self, evt):
        self._escape()
        evt.Skip()

    def _escape(self):
        self._keys_pressed.clear()
        self._release_mouse()

    def _on_resize(self, event):
        self.set_size(*event.GetSize())

    def set_size(self, width, height):
        glViewport(0, 0, width, height)
        if height > 0:
            self._render_world.aspect_ratio = width / height
        else:
            self._render_world.aspect_ratio = 1
        self.DoSetSize(0, 0, width, height, 0)  # I don't know if this is how you are supposed to do this

    def _on_draw(self, event):
        self.draw()
        event.Skip()

    def draw(self):
        glClear(GL_COLOR_BUFFER_BIT | GL_DEPTH_BUFFER_BIT)
        self._render_world.draw()
        self.SwapBuffers()

    def _gc(self, event):
        self._render_world.run_garbage_collector()
        event.Skip()


class World3DPanel(BaseWorldProgram):
    def __init__(self, parent: 'MainFrame', world: 'World'):
        super().__init__(parent, wx.HORIZONTAL)
        self._world = world
        self._canvas: Optional[World3dCanvas] = None
        self._temp = wx.StaticText(
            self,
            wx.ID_ANY,
            'Please wait while the renderer loads',
            wx.DefaultPosition,
            wx.DefaultSize,
            0,
        )
        self._menu = None
        self._menu_buttons = []
        self._operation_choice: Optional[SimpleChoiceAny] = None
        self._options_button: Optional[wx.Button] = None
        self._temp.SetFont(wx.Font(40, wx.DECORATIVE, wx.NORMAL, wx.NORMAL))
        self.Bind(wx.EVT_SIZE, self._on_resize)

    def _on_resize(self, event):
        if self._canvas is not None:
            self._canvas.SetSize(self.GetSize()[0], self.GetSize()[1])
        event.Skip()

    def _undo_event(self, evt):
        self._world.undo()

    def _redo_event(self, evt):
        self._world.redo()

    def _save_event(self, evt):
        self._world.save()

    def _operation_selection_change(self, evt):
        self._operation_selection_change_()
        evt.Skip()

    def _operation_selection_change_(self):
        operation_path = self._operation_choice.GetAny()
        operation = operations.operations[operation_path]
        if "options" in operation.get("inputs", []) or "wxoptions" in operation.get("inputs", []):
            self._options_button.Enable()
        else:
            self._options_button.Disable()

    def _change_options(self, evt):
        operation_path = self._operation_choice.GetAny()
        operation = operations.operations[operation_path]
        if "options" in operation.get("inputs", []):
            pass  # TODO: implement this
        elif "wxoptions" in operation.get("inputs", []):
            options = operation["wxoptions"](self, self._world, operations.options.get(operation_path, {}))
            if isinstance(options, dict):
                operations.options[operation_path] = options
            else:
                log.error(f"Plugin {operation['name']} at {operation_path} did not return options in a valid format")

    def _get_box(self) -> Optional[Selection]:
        box = self._canvas._render_world._selection_box  # TODO: make a way to publicly access this
        if box.select_state == 2:
            return Selection(
                (SubSelectionBox(
                    box.min,
                    box.max
                ),)
            )
        else:
            wx.MessageBox("You must select an area of the world before running this operation")
            return None

    def _run_operation(self, evt):
        operation_path = self._operation_choice.GetAny()
        operation = operations.operations[operation_path]
        operation_input_definitions = operation.get("inputs", [])
        if "dst_box" in operation_input_definitions or "dst_box_multiple" in operation_input_definitions:
            if "structure_callable" in operation:
                operation_inputs = []
                for inp in operation_input_definitions:
                    if inp == "src_box":
                        selection = self._get_box()
                        if selection is None:
                            return
                        operation_inputs.append(selection)

                    elif inp in ["options", "wxoptions"]:
                        operation_inputs.append(operations.options.get(operation_path, {}))

                structure = self._world.run_operation(operation["structure_callable"], *operation_inputs, create_undo=False)
                if not isinstance(structure, Structure):
                    wx.MessageBox("Object returned from structure_callable was not a Structure. Aborting.")
                    return
            elif "src_box" in operation_input_definitions:
                selection = self._get_box()
                if selection is None:
                    return
                structure = Structure.from_world(self._world, selection, self._canvas._render_world.dimension)
            else:
                wx.MessageBox("This should not happen")
                return

            if "dst_box" in operation_input_definitions:
                # trigger UI to show select box UI
                raise NotImplementedError

            elif "dst_box_multiple" in operation_input_definitions:
                # trigger UI to show select box multiple UI
                raise NotImplementedError

        else:
            self._run_main_operation(operation_path, operation, operation_input_definitions)

    def _run_main_operation(self, operation_path, operation, operation_input_definitions, dst_box=None, dst_box_multiple=None, structure=None):
        operation_inputs = []
        for inp in operation_input_definitions:
            if inp == "src_box":
                selection = self._get_box()
                if selection is None:
                    return
                operation_inputs.append(selection)

            elif inp == "dst_box":
                operation_inputs.append(dst_box)
            elif inp == "dst_box_multiple":
                operation_inputs.append(dst_box_multiple)
            elif inp == "structure":
                operation_inputs.append(structure)
            elif inp in ["options", "wxoptions"]:
                operation_inputs.append(operations.options.get(operation_path, {}))

        self._world.run_operation(operation["operation"], *operation_inputs)

    def enable(self):
        if self._canvas is None:
            self.Update()
            self._menu = SimplePanel(self)
            self.add_object(self._menu, 0, wx.EXPAND)
            self._menu.Bind(wx.EVT_MOTION, self._steal_focus)

            for text, operation in [
                ['Undo', self._undo_event],
                ['Redo', self._redo_event],
                ['Save', self._save_event],
                ['Close', self._close_world]
            ]:
                button = wx.Button(
                    self._menu,
                    wx.ID_ANY,
                    text,
                    wx.DefaultPosition,
                    wx.DefaultSize,
                    0,
                )
                button.Bind(wx.EVT_BUTTON, operation)
                self._menu.add_object(button, 0)
                self._menu_buttons.append(
                    button
                )
            self._operation_choice = SimpleChoiceAny(self._menu)
            self._operation_choice.SetItems({key: value["name"] for key, value in operations.operations.items()})
            self._operation_choice.Bind(wx.EVT_CHOICE, self._operation_selection_change)
            self._menu.add_object(self._operation_choice, 0)
            self._options_button = wx.Button(
                self._menu,
                label="Change Options"
            )
            run_button = wx.Button(
                self._menu,
                label="Run Operation"
            )
            self._options_button.Bind(wx.EVT_BUTTON, self._change_options)
            run_button.Bind(wx.EVT_BUTTON, self._run_operation)
            self._menu.add_object(self._options_button)
            self._menu.add_object(run_button)
            self._operation_selection_change_()

            self._canvas = World3dCanvas(self, self._world)
            self.add_object(self._canvas, 0, wx.EXPAND)
            self._temp.Destroy()
            self.GetParent().Layout()
            self._menu.Fit()
            self.Update()
        self._canvas.set_size(self.GetSize()[0], self.GetSize()[1])
        self._canvas.draw()
        self._canvas.Update()
        self._canvas.enable()

    def disable(self):
        if self._canvas is not None:
            self._canvas.disable()

    def close(self):
        self.disable()
        if self._canvas is not None:
            self._canvas.close()

    def is_closeable(self):
        if self._canvas is not None:
            return self._canvas.is_closeable()
        return True

    def _close_world(self, evt):
        self.GetGrandParent().GetParent().close_world(self._world.world_path)

    def _steal_focus(self, evt):
        self._menu.SetFocus()
        evt.Skip()


if __name__ == "__main__":
    class MainFrame(wx.Frame):
        def __init__(self):
            self.size = (400, 300)
            wx.Frame.__init__(self, None, title="3D World View", size=self.size,
                              style=wx.DEFAULT_FRAME_STYLE | wx.FULL_REPAINT_ON_RESIZE)
            self.SetMinSize(self.size)
            self.Bind(wx.EVT_CLOSE, self.on_close)

            world_path = sys.argv[1]
            import amulet.world_interface
            world = amulet.world_interface.load_world(world_path)

            self.panel = World3DPanel(self, world)

        def on_close(self, event):
            self.Destroy()
            sys.exit(0)


    class App(wx.App):
        def OnInit(self):
            frame = MainFrame()
            frame.Show()
            return True

    app = App()
    app.MainLoop()