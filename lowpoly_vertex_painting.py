import bpy
import bmesh
from bpy_extras import view3d_utils
from mathutils import Quaternion, Vector
from collections import deque


bl_info = {
    "name": "Low-Poly Vertex Painting",
    "description": "Tools to improve low-poly vertex painting.",
    "author": "Luca Harris",
    "version": (0, 1),
    "wiki_url": "https://github.com/lucatronica/blender-lowpoly-vertex-painting",
    "blender": (2, 90, 0),
    "category": "3D View",
}


def fill_op_main(context, x, y, color, mode):
    obj = context.vertex_paint_object
    region = context.region
    rv3d = context.region_data
    coord = x, y

    # get object rotation
    rotation_quaternion = Quaternion()
    if obj.rotation_mode == "QUATERNION":
        rotation_quaternion = obj.rotation_quaternion
    elif obj.rotation_mode == "AXIS_ANGLE":
        axis = obj.rotation_axis_angle[:3]
        angle = obj.rotation_axis[3]
        rotation_quaternion = Quaternion(axis, angle)
    else:
        rotation_quaternion = obj.rotation_euler.to_quaternion()

    # get mouse ray in object space
    ray_origin = obj.matrix_world.inverted() @ view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    ray_direction = rotation_quaternion.inverted() @ view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

    # ray cast
    result, location, normal, index = obj.ray_cast(ray_origin, ray_direction)

    if result:
        color4 = Vector((color[0], color[1], color[2], 1.0))
        me = obj.data
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.faces.ensure_lookup_table()
        face = bm.faces[index]

        if mode == "SINGLE":
            fill_faces(bm, [face], color4)
        elif mode == "CONNECTED":
            fill_connected_faces(bm, [face], color4, False)
        elif mode == "CONNECTED_COLOR":
            fill_connected_faces(bm, [face], color4, True)
        
        bm.to_mesh(me)
        bm.free()
        me.update()

    
    return result

def select_linked_by_color_op_main(context):
    me = context.edit_object.data
    bm = bmesh.from_edit_mesh(me)
    
    for face in connected_faces(bm, filter(lambda face : face.select, bm.faces), True):
        face.select = True
    
    bmesh.update_edit_mesh(me, destructive=False, loop_triangles=False)
    me.update()


# returns  a set of indices of all connected polygons
def connected_faces(bm, faces, same_color):
    color_layer = bm.loops.layers.color.active
    face_set = set(faces)
    target_color = face_color(color_layer, next(iter(face_set))) if same_color else None
    face_queue = deque(face_set);

    while len(face_queue) > 0:
        face = face_queue.pop()
        
        for edge in face.edges:
            for connected_face in edge.link_faces:
                if connected_face not in face_set and (not same_color or vector4_equal(target_color, face_color(color_layer, connected_face))):
                    face_set.add(connected_face);
                    face_queue.appendleft(connected_face)
    
    return face_set

# get the average vertex color of a face
def face_color(color_layer, face):
    total = Vector((0.0, 0.0, 0.0, 0.0))

    for loop in face.loops:
        total += loop[color_layer]
    
    return total / len(face.loops)

# if two vector4s are approximately equal
def vector4_equal(v1, v2):
    return (v1 - v2).length_squared < 0.004

# fill connected faces with the given color
def fill_connected_faces(bm, faces, new_color, same_color):
    fill_faces(bm, connected_faces(bm, faces, same_color), new_color)

# fill the given faces with the given color
def fill_faces(bm, faces, new_color):
    color_layer = bm.loops.layers.color.active
    for face in faces:
        for loop in face.loops:
            loop[color_layer] = new_color


class VertexPaintFillOperator(bpy.types.Operator):
    bl_idname = "paint.vertex_fill"
    bl_label = "Vertex Paint Fill"
    bl_options = {"UNDO"}

    x: bpy.props.IntProperty()
    y: bpy.props.IntProperty()

    color: bpy.props.FloatVectorProperty(
        name="Color",
        description="Set's the fill color",
        subtype="COLOR_GAMMA",
        default=(1.0, 1.0, 1.0),
        min=0.0,
        max=1.0,
    )

    mode: bpy.props.EnumProperty(
        name="Mode",
        description="Set which faces the fill selects",
        items=(
            ("SINGLE", "Single", "Fills only the chosen face"),
            ("CONNECTED", "Linked", "Fills the chosen face and all connected faces"),
            ("CONNECTED_COLOR", "Linked Color", "Fills the chosen face and all connected faces with the same color"),
        ),
        default="SINGLE",
    )

    def execute(self, context):
        fill_op_main(context, self.x, self.y, self.color, self.mode)
        return {"FINISHED"}
    
    def invoke(self, context, event):
        self.x = event.mouse_region_x
        self.y = event.mouse_region_y
        return self.execute(context)


class VertexPaintFillTool(bpy.types.WorkSpaceTool):
    bl_space_type = "VIEW_3D"
    bl_context_mode = "PAINT_VERTEX"
    bl_idname = "vertex_paint_fill"
    bl_label = "Fill"
    bl_description = "Set vertex colors of faces using active color"
    bl_icon = "ops.paint.weight_fill"
    bl_widget = None
    bl_keymap = (
        (VertexPaintFillOperator.bl_idname, {"type": "LEFTMOUSE", "value": "PRESS"}, {}),
    )

    def draw_settings(context, layout, tool):
        props = tool.operator_properties(VertexPaintFillOperator.bl_idname)
        layout.prop(props, "color", text="")
        layout.prop(props, "mode", text="")


class SelectLinkedFacesByVertexColor(bpy.types.Operator):
    """Selected linked faces by vertex color."""
    bl_idname = "mesh.select_linked_vertex_color"
    bl_label = "Select Linked Faces by Vertex Color"
    bl_options = {"UNDO", "REGISTER"}

    @classmethod
    def poll(cls, context):
        obj = context.edit_object
        return (obj is not None and obj.data.total_face_sel > 0)

    def execute(self, context):
        self.report({"INFO"}, str(select_linked_by_color_op_main(context)))
        return {"FINISHED"}

def mesh_edit_select_menu_draw(self, context):
    layout = self.layout
    layout.operator(SelectLinkedFacesByVertexColor.bl_idname, text="Vertex Color")


classes = (
    VertexPaintFillOperator,
    SelectLinkedFacesByVertexColor,
)

def register():
    bpy.utils.register_tool(VertexPaintFillTool, separator=True)
    bpy.types.VIEW3D_MT_edit_mesh_select_linked.append(mesh_edit_select_menu_draw)
    for class_ in classes:
        bpy.utils.register_class(class_)

def unregister():
    bpy.utils.unregister_tool(VertexPaintFillTool)
    bpy.types.VIEW3D_MT_edit_mesh_select_linked.remove(mesh_edit_select_menu_draw)
    for class_ in classes:
        bpy.utils.unregister_class(class_)

# testing
if __name__ == "__main__":
    register()
