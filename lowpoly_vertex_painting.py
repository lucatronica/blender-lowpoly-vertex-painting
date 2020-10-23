import bpy
from bpy_extras import view3d_utils
from mathutils import Quaternion
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

id_prefix = "lowpoly_vertex_painting."


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
        color4 = tuple(color) + (1.0,)
        me = obj.data

        if mode == "SINGLE":
            fill_polygons(me, (index,), color4)
        elif mode == "CONNECTED":
            fill_connected_polygons(me, index, color4, False)
        elif mode == "CONNECTED_COLOR":
            fill_connected_polygons(me, index, color4, True)

    
    return result


# returns  a set of indices of all connected polygons
def connected_polygons(me, polygon_index, same_color):
    # generate edge -> polygon dictionary
    edge_polygon_dict = dict()

    for polygon in me.polygons:
        for loop_index in polygon.loop_indices:
            edge_index = me.loops[loop_index].edge_index
            
            if edge_index in edge_polygon_dict:
                edge_polygon_dict[edge_index].add(polygon.index)
            else:
                edge_polygon_dict[edge_index] = {polygon.index}
    
    # breadth-first-search for related polygons
    shared_color = polygon_color(me, polygon_index)
    polygon_set = set((polygon_index,))
    index_queue = deque((polygon_index,));

    while len(index_queue) > 0:
        index = index_queue.pop()
        
        for loop_index in me.polygons[index].loop_indices:
            for connected_index in edge_polygon_dict[me.loops[loop_index].edge_index]:
                if connected_index not in polygon_set and (not same_color or colors_equal(me, shared_color, polygon_color(me, connected_index))):
                    polygon_set.add(connected_index);
                    index_queue.appendleft(connected_index)
            
    return polygon_set

# fill connected polygons with the given color
def fill_connected_polygons(me, polygon_index, new_color, same_color):
    fill_polygons(me, connected_polygons(me, polygon_index, same_color), new_color)

# fill the given polygons with the given color
def fill_polygons(me, polygon_indices, new_color):
    colors = me.vertex_colors.active.data
    for index in polygon_indices:
        for loop_index in me.polygons[index].loop_indices:
            colors[loop_index].color = new_color

# if two color4s are approximately equal
def colors_equal(me, c1, c2):
    return abs(c1[0] - c2[0]) + abs(c1[1] - c2[1]) + abs(c1[2] - c2[2]) + abs(c1[3] - c2[3]) < 0.004

# average polygon color
def polygon_color(me, polygon_index):
    colors = me.vertex_colors.active.data
    polygon = me.polygons[polygon_index]

    r = 0.0
    g = 0.0
    b = 0.0
    a = 0.0

    for loop_index in polygon.loop_indices:
        color = colors[loop_index].color
        r += color[0]
        g += color[1]
        b += color[2]
        a += color[3]
    
    return (r / polygon.loop_total, g / polygon.loop_total, b / polygon.loop_total, a / polygon.loop_total)


class VertexPaintFillOperator(bpy.types.Operator):
    bl_idname = id_prefix + "vertex_paint_fill"
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
    bl_idname = id_prefix + "vertex_paint_fill"
    bl_label = "Fill"
    bl_description = "Fills a face with the active color"
    bl_icon = "ops.paint.weight_fill"
    bl_widget = None
    bl_keymap = (
        (VertexPaintFillOperator.bl_idname, {"type": "LEFTMOUSE", "value": "PRESS"}, {}),
    )

    def draw_settings(context, layout, tool):
        props = tool.operator_properties(VertexPaintFillOperator.bl_idname)
        layout.prop(props, "color", text="")
        layout.prop(props, "mode", text="")


classes = (
    VertexPaintFillOperator,
)

def register():
    bpy.utils.register_tool(VertexPaintFillTool, separator=True)
    for class_ in classes:
        bpy.utils.register_class(class_)

def unregister():
    bpy.utils.unregister_tool(VertexPaintFillTool)
    for class_ in classes:
        bpy.utils.unregister_class(class_)

# testing
if __name__ == "__main__":
    register()
