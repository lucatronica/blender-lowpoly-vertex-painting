import bpy
import bmesh
from bpy_extras import view3d_utils
from mathutils import Quaternion, Vector, Color
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

PROP_PREFIX =  "vertex_paint_"
FILL_COLOR = PROP_PREFIX + "fill_color"


# pick vertex color at index, using weighted average of surrounding points
# returns (result, color4, index)
def pick_vertex_color(context, obj, region_x, region_y):
    # get mouse ray in object space
    region = context.region
    rv3d = context.region_data
    coord = region_x, region_y
    world_ray_origin = view3d_utils.region_2d_to_origin_3d(region, rv3d, coord)
    world_ray_direction = view3d_utils.region_2d_to_vector_3d(region, rv3d, coord)

    mwi = obj.matrix_world.inverted()
    ray_origin = mwi @ world_ray_origin
    ray_direction = (mwi @ (world_ray_origin + world_ray_direction)) - ray_origin

    # ray cast
    result, location, normal, index = obj.ray_cast(ray_origin, ray_direction)

    color = Vector((0.0, 0.0, 0.0, 0.0))
    if result:
        me = obj.data
        colors = me.vertex_colors.active.data
        location_vector = Vector(location)
        total = 0.0

        for loop_index in me.polygons[index].loop_indices:
            loop_position = me.vertices[me.loops[loop_index].vertex_index].co
            distance = (location_vector - loop_position).length
            total += distance

            loop_color = colors[loop_index].color
            color[0] += loop_color[0] * distance
            color[1] += loop_color[1] * distance
            color[2] += loop_color[2] * distance
            color[3] += loop_color[3] * distance
        
        if total > 0.0:
            color /= total

    return result, color, index

# returns a set of loops
def connected_loops(bm, starting_faces, color=None, tolerance=0.001, traverse_vertices=False, selected_faces=False, selected_vertices=False):
    color_layer = bm.loops.layers.color.active
    
    face_set = set(starting_faces)
    face_queue = deque(face_set);
    loop_set = set()

    if color is None:
        color = face_color(bm, next(iter(face_set)))

    while len(face_queue) > 0:
        face = face_queue.pop()

        # make sure we can visit this face
        if not selected_faces or face.select:
            # inspect all loops on this face
            for loop in face.loops:
                if color_equal(loop[color_layer], color, tolerance):
                    # save loop if we're allowed to
                    if not selected_vertices or loop.vert.select:
                        loop_set.add(loop)

                    # see if we can travel to neighboring faces :)
                    for connected_loop in (loop.vert.link_loops if traverse_vertices else loop.link_loops):
                        connected_face = connected_loop.face
                        if connected_face not in face_set and color_equal(connected_loop[color_layer], color, tolerance):
                            face_set.add(connected_face)
                            face_queue.appendleft(connected_face)
    
    return loop_set

# if two color vector4s are equal
def color_equal(v1, v2, tolerance):
    return (v1 - v2).length_squared / 3.0 <= tolerance

# average color of a face
def face_color(bm, face):
    color_layer = bm.loops.layers.color.active

    color = Vector((0.0, 0.0, 0.0, 0.0))
    for loop in face.loops:
        color += loop[color_layer]

    return color / len(face.loops)


# sample vertex operator
class VertexPaintColorSample(bpy.types.Operator):
    """Sample vertex color."""
    bl_idname = "paint.vertex_color_sample"
    bl_label = "Sample vertex color"

    x: bpy.props.IntProperty()
    y: bpy.props.IntProperty()

    def execute(self, context):
        result, color, _ = pick_vertex_color(context, bpy.context.active_object, self.x, self.y)
        if result:
            set_fill_color(None, Color(color[:3]))
        return {"FINISHED"}
    
    def invoke(self, context, event):
        self.x = event.mouse_region_x
        self.y = event.mouse_region_y
        return self.execute(context)


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

    tolerance: bpy.props.FloatProperty(
        name="Tolerance",
        description="Controls the similarity for colors to be considered equal. A lower value means only more similar colors will be selected",
        subtype ="FACTOR",
        default=0.005,
        precision=3,
        min=0.0,
        max=1.0,
    )

    vertices: bpy.props.BoolProperty(
        name="Traverse Vertices",
        description="If enabled then the fill will traverse vertex corners",
        default=False,
    )

    def execute(self, context):
        fill_op_main(context, self.x, self.y, self.color, self.tolerance, self.vertices)
        return {"FINISHED"}
    
    def invoke(self, context, event):
        self.x = event.mouse_region_x
        self.y = event.mouse_region_y
        return self.execute(context)

def fill_op_main(context, x, y, color, tolerance, traverse_vertices):
    obj = context.vertex_paint_object

    result, target_color, index = pick_vertex_color(context, obj, x, y)

    if result:
        me = obj.data
        bm = bmesh.new()
        bm.from_mesh(me)
        bm.faces.ensure_lookup_table()
        face = bm.faces[index]

        color4 = Vector((color[0], color[1], color[2], 1.0))
        color_layer = bm.loops.layers.color.active

        for loop in connected_loops(bm, [face], color=target_color, tolerance=tolerance, traverse_vertices=traverse_vertices, selected_faces=me.use_paint_mask, selected_vertices=me.use_paint_mask_vertex):
            loop[color_layer] = color4
        
        bm.to_mesh(me)
        bm.free()
        me.update()


class VertexPaintFillTool(bpy.types.WorkSpaceTool):
    bl_space_type = "VIEW_3D"
    bl_context_mode = "PAINT_VERTEX"
    bl_idname = "vertex_paint_fill"
    bl_label = "Fill"
    bl_description = "Fill connected faces with the active color"
    bl_icon = "ops.paint.weight_fill"
    bl_widget = None
    bl_keymap = (
        (VertexPaintFillOperator.bl_idname, {"type": "LEFTMOUSE", "value": "PRESS"}, {}),
        (VertexPaintColorSample.bl_idname, {"type": "S", "value": "PRESS"}, {}),
    )

    def draw_settings(context, layout, tool):
        props = tool.operator_properties(VertexPaintFillOperator.bl_idname)
        layout.prop(props, "color", text="")
        layout.prop(props, "tolerance")
        layout.prop(props, "vertices")


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
        select_linked_by_color_op_main(context)
        return {"FINISHED"}

def select_linked_by_color_op_main(context):
    me = context.edit_object.data
    bm = bmesh.from_edit_mesh(me)
    
    for loop in connected_loops(bm, filter(lambda face : face.select, bm.faces), traverse_vertices=True):
        loop.vert.select = True
    
    bmesh.update_edit_mesh(me, destructive=False, loop_triangles=False)
    me.update()

def mesh_edit_select_menu_draw(self, context):
    layout = self.layout
    layout.operator(SelectLinkedFacesByVertexColor.bl_idname, text="Vertex Color")


classes = (
    VertexPaintFillOperator,
    SelectLinkedFacesByVertexColor,
    VertexPaintColorSample,
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
