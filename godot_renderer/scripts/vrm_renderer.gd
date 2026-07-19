extends Node3D

const VRM_PATH = "res://models/avatar.vrm"
const PORT = 39539

var _udp: PacketPeerUDP = PacketPeerUDP.new()
var _vrm_instance: Node = null
var _skeleton: Skeleton3D = null
var _loading = false
var _progress = [0.0]

func _ready():
	print("=== Naixi VRM Renderer ===")
	
	var sky = WorldEnvironment.new()
	var env = Environment.new()
	env.background_mode = Environment.BG_COLOR
	env.background_color = Color(0.1, 0.1, 0.15)
	env.ambient_light_color = Color(0.6, 0.6, 0.6)
	sky.environment = env
	add_child(sky)
	
	var cam = Camera3D.new()
	cam.position = Vector3(0, 0.8, 3.0)
	cam.look_at(Vector3(0, 0.5, 0))
	cam.fov = 40
	cam.current = true
	add_child(cam)
	
	var l1 = DirectionalLight3D.new()
	l1.rotation = Vector3(-0.4, 0.8, 0)
	l1.light_energy = 1.5
	add_child(l1)
	var l2 = DirectionalLight3D.new()
	l2.rotation = Vector3(0.4, -0.3, 0)
	l2.light_energy = 0.5
	add_child(l2)
	
	# 后台加载
	var err = ResourceLoader.load_threaded_request(VRM_PATH)
	if err == OK:
		_loading = true
		print("后台加载中...")
	else:
		print("加载失败: err=", err)
		print("需要启用 VRM 插件: 项目 → 项目设置 → 插件 → 启用 VRM")
	
	_udp.bind(PORT)

func _process(_delta):
	if _loading:
		var st = ResourceLoader.load_threaded_get_status(VRM_PATH, _progress)
		if st == ResourceLoader.THREAD_LOAD_IN_PROGRESS:
			return
		_loading = false
		if st == ResourceLoader.THREAD_LOAD_LOADED:
			var scene = ResourceLoader.load_threaded_get(VRM_PATH)
			if scene:
				_vrm_instance = scene.instantiate()
				if _vrm_instance:
					_vrm_instance.position = Vector3(0, 0, 0)
					add_child(_vrm_instance)
					_find_skeleton(_vrm_instance)
					print("✓ 加载成功")
				else:
					print("✗ 实例化失败")
			else:
				print("✗ 获取资源失败")
		else:
			print("✗ 加载状态: ", st)
	
	while _udp.get_available_packet_count() > 0:
		var data = _udp.get_packet().get_string_from_utf8()
		_handle_vmc(data)

func _find_skeleton(n):
	if n is Skeleton3D: _skeleton = n; return
	for c in n.get_children(): _find_skeleton(c)

func _handle_vmc(s):
	if not _skeleton: return
	var j = JSON.new()
	if j.parse(s) != OK: return
	var m = j.data
	if typeof(m) != TYPE_DICTIONARY: return
	var bones = m.get("bones", {})
	if typeof(bones) != TYPE_DICTIONARY: return
	for name in bones:
		var idx = _find_bone(name)
		if idx >= 0:
			_skeleton.set_bone_pose_rotation(idx, Quaternion(Vector3(0,0,1), deg_to_rad(float(bones[name]))))

func _find_bone(name):
	if not _skeleton: return -1
	for i in _skeleton.get_bone_count():
		if _skeleton.get_bone_name(i).to_lower() == name.to_lower(): return i
	for i in _skeleton.get_bone_count():
		if name.to_lower() in _skeleton.get_bone_name(i).to_lower(): return i
	return -1
