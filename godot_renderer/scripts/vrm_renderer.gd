extends Node

# VRM 渲染控制器 — 加载 VRM 模型 + UDP 接收骨骼数据
# 监听 39539 端口，接收 JSON 骨骼变换 → 应用到 VRM 骨架

const PORT = 39539
const VRM_PATH = "res://models/avatar.vrm"

@onready var _udp = PacketPeerUDP.new()
var _vrm_node: Node = null
var _skeleton: Skeleton3D = null

func _ready():
	# 启动 UDP 监听
	if _udp.bind(PORT) != OK:
		print("VMC: UDP 端口 %d 绑定失败" % PORT)
		return
	print("VMC: 监听端口 %d" % PORT)
	
	# 加载 VRM 模型
	_load_vrm()

func _load_vrm():
	if not ResourceLoader.exists(VRM_PATH):
		print("VRM: 模型文件不存在: %s" % VRM_PATH)
		return
	var scene = load(VRM_PATH)
	if not scene:
		return
	_vrm_node = scene.instantiate()
	add_child(_vrm_node)
	
	# 查找骨骼
	_find_skeleton(_vrm_node)
	if _skeleton:
		print("VRM: 加载成功，骨骼数: %d" % _skeleton.get_bone_count())
	else:
		print("VRM: 未找到骨骼")

func _find_skeleton(node: Node):
	if node is Skeleton3D:
		_skeleton = node
		return
	for child in node.get_children():
		_find_skeleton(child)

func _process(delta):
	# 接收 UDP 数据
	while _udp.get_available_packet_count() > 0:
		var data = _udp.get_packet().get_string_from_utf8()
		_parse_vmc(data)

func _parse_vmc(json_str: String):
	var test = JSON.new()
	var err = test.parse(json_str)
	if err != OK:
		return
	var msg = test.data
	if typeof(msg) != TYPE_DICTIONARY:
		return
	
	# 骨骼变换: {"bones": {"Head": 15.0, "LeftUpperArm": -30.0, ...}}
	var bones = msg.get("bones", {})
	if typeof(bones) != TYPE_DICTIONARY or not _skeleton:
		return
	
	for bone_name in bones:
		var angle = bones[bone_name]
		var bone_idx = _find_bone(bone_name)
		if bone_idx >= 0:
			# Godot 使用弧度，传入的是角度
			_skeleton.set_bone_pose_rotation(bone_idx, Quaternion(Vector3(0, 0, 1), deg_to_rad(angle)))

func _find_bone(name: String) -> int:
	if not _skeleton:
		return -1
	for i in _skeleton.get_bone_count():
		if _skeleton.get_bone_name(i).to_lower() == name.to_lower():
			return i
	# 尝试模糊匹配
	for i in _skeleton.get_bone_count():
		var bname = _skeleton.get_bone_name(i).to_lower()
		if name.to_lower() in bname or bname in name.to_lower():
			return i
	return -1
