"""Deterministic editable white-clay alpine scene. Run with Blender --background --python.
B01 real geometry; B02 reference composition; B03 shared white material; B04 depth.
Only writes alongside this script. No image assets or external dependencies.
"""
import bpy, math, random, os, json
from mathutils import Vector, noise
from math import sin, cos, pi

OUT = os.path.dirname(os.path.abspath(__file__))
random.seed(260926)
bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene
scene.unit_settings.system = 'METRIC'

def collection(name):
    c = bpy.data.collections.new(name); scene.collection.children.link(c); return c
cols = {n: collection(n) for n in ['01_Far_Ranges','02_Main_Peak','03_Shore_Terrain',
    '04_Forest_Left','05_Forest_Right','06_Lake','07_Foreground_Rocks',
    '08_Foreground_Plants','09_Overhanging_Branch','10_Camera_Studio']}
mat = bpy.data.materials.new('Clay • uniform matte white')
mat.diffuse_color = (0.82,0.82,0.82,1)
mat.use_nodes = True
p = mat.node_tree.nodes.get('Principled BSDF')
p.inputs['Base Color'].default_value = (0.82,0.82,0.82,1)
p.inputs['Roughness'].default_value = 0.88
p.inputs['Specular IOR Level'].default_value = 0.22

def mesh(name, verts, faces, group, smooth=False):
    m = bpy.data.meshes.new(name); m.from_pydata(verts,[],faces); m.update()
    m.materials.append(mat)
    for f in m.polygons: f.use_smooth = smooth
    ob = bpy.data.objects.new(name,m); cols[group].objects.link(ob); return ob

class Builder:
    def __init__(self): self.v=[]; self.f=[]
    def tube(self, a,b,r1,r2,steps=8):
        a,b=Vector(a),Vector(b); d=(b-a).normalized()
        u=d.cross(Vector((0,0,1)))
        if u.length<0.01: u=d.cross(Vector((0,1,0)))
        u.normalize(); w=d.cross(u).normalized(); k=len(self.v)
        for point,r in [(a,r1),(b,r2)]:
            for i in range(steps): self.v.append(tuple(point+r*(cos(i*2*pi/steps)*u+sin(i*2*pi/steps)*w)))
        self.f.append(tuple(k+i for i in reversed(range(steps))))
        self.f.append(tuple(k+steps+i for i in range(steps)))
        for i in range(steps): self.f.append((k+i,k+(i+1)%steps,k+(i+1)%steps+steps,k+i+steps))
    def leaf(self,center,length,width,angle,tilt=0):
        c=Vector(center); d=Vector((cos(angle),sin(angle),tilt)).normalized(); s=Vector((-sin(angle)*.65,cos(angle)*.65,.76))
        k=len(self.v)
        # Solid folded lanceolate leaf, not a textured billboard.
        points=[c-d*length*.5,c-s*width*.5,c+d*length*.5,c+s*width*.5,c+Vector((0,0,width*.16)),c-Vector((0,0,width*.07))]
        self.v.extend(tuple(p) for p in points)
        for i in range(4):
            self.f.append((k+i,k+(i+1)%4,k+4)); self.f.append((k+(i+1)%4,k+i,k+5))
    def obj(self,name,group,smooth=False): return mesh(name,self.v,self.f,group,smooth)

def relief(x,y,scale=1):
    return noise.multi_fractal(Vector((x*.045,y*.045,3.7)),1.05,2.1,4)*scale

mountain_specs=[]
def height_at(x,y,peaks):
    h=.05
    for px,py,height,rx,ry in peaks:
        dx=(x-px)/rx; dy=(y-py)/ry; a=math.atan2(dy,dx)
        r=math.sqrt(dx*dx+dy*dy)*(1+.12*sin(a*7)+.07*cos(a*11))
        h=max(h,height*max(0,1-r)**1.18)
    return (h+min(1,h/10)*(relief(x,y,2)+.75*sin(x*.65+y*.23)))*.64-.8

def mountain(name, bounds, peaks, group, step=2.0):
    mountain_specs.append((bounds,peaks))
    xmin,xmax,ymin,ymax=bounds; nx=int((xmax-xmin)/step); ny=int((ymax-ymin)/step)
    v=[]; f=[]
    for j in range(ny+1):
        y=ymin+(ymax-ymin)*j/ny
        for i in range(nx+1):
            x=xmin+(xmax-xmin)*i/nx
            v.append((x,y,height_at(x,y,peaks)))
    for j in range(ny):
        for i in range(nx):
            a=j*(nx+1)+i; b=a+1; c=a+nx+1; d=c+1
            f.extend([(a,b,c),(b,d,c)] if (i+j)%2 else [(a,b,d),(a,d,c)])
    # Close terrain around perimeter with skirt and bottom.
    ring=list(range(nx+1))+[j*(nx+1)+nx for j in range(1,ny+1)]+[ny*(nx+1)+i for i in reversed(range(nx))]+[j*(nx+1) for j in reversed(range(1,ny))]
    k=len(v); v.extend((v[a][0],v[a][1],-3) for a in ring)
    for i,a in enumerate(ring): f.append((a,k+i,k+(i+1)%len(ring),ring[(i+1)%len(ring)]))
    f.append(tuple(k+i for i in reversed(range(len(ring)))))
    return mesh(name,v,f,group)

mountain('Distant alpine ridge / 520m',(-250,250,410,600),[(x,480+random.uniform(-15,15),random.uniform(35,63),65,88) for x in range(-220,241,38)],'01_Far_Ranges',2.8)
mountain('Far alpine ridge / 365m',(-180,180,300,460),[(x,370+random.uniform(-15,15),random.uniform(26,49),50,80) for x in range(-160,171,32)],'01_Far_Ranges',2.2)
mountain('RIGHT • dominant summit',(-10,170,160,335),[(63,245,66,60,83),(104,269,59,65,78),(32,236,39,46,74),(143,278,60,52,72)],'02_Main_Peak',1.4)
mountain('Left valley massif',(-175,-14,160,332),[(-115,231,43,67,80),(-61,223,25,50,73),(-154,250,47,67,80)],'02_Main_Peak',1.7)

def bank_edge(y,side):
    return (-18-.14*(y+20)+3.6*sin(y*.04)+24*math.exp(-((y+48)/19)**2)) if side<0 else (23+.12*(y+20)+5*sin(y*.029))
def bank_z(x,y,side):
    d=(x-bank_edge(y,side))*side
    return .12+max(0,d)*.075+max(0,relief(x,y,.45))*.5

for side in [-1,1]:
    v=[]; f=[]; nx=28; ny=105
    for j in range(ny+1):
        y=-48+j*3.2
        for i in range(nx+1):
            d=i*3.5; x=bank_edge(y,side)+side*d
            v.append((x,y,bank_z(x,y,side) if i else -.12))
    for j in range(ny):
        for i in range(nx):
            a=j*(nx+1)+i; f.extend([(a,a+1,a+nx+2),(a,a+nx+2,a+nx+1)])
    if side<0: f=[tuple(reversed(face)) for face in f]
    mesh(('Left' if side<0 else 'Right')+' sculpted lakeshore',v,f,'03_Shore_Terrain',True)

# Water stays a truly horizontal, editable mesh with tiny geometric undulations.
v=[]; f=[]; nx=160; ny=200
for j in range(ny+1):
    y=-70+j*2
    for i in range(nx+1):
        x=-180+i*2.25
        z=.011*sin(y*1.8+x*.23)+.006*sin(y*3.4-x*.11)
        v.append((x,y,z))
for j in range(ny):
    for i in range(nx):
        a=j*(nx+1)+i; f.append((a,a+1,a+nx+2,a+nx+1))
mesh('Calm lake • modeled shallow ripples',v,f,'06_Lake',True)

# Shared real meshes: each tree is individually selectable / movable.
tree_data=[]
for variant in range(6):
    b=Builder(); b.tube((0,0,0),(0,0,1),.035,.008)
    for tier in range(7):
        z=.19+tier*.103; r=(1-z)*(.25+variant*.006)
        k=len(b.v); n=18
        for level,rr in [(0,r*.75),(.025,r),(.15, r*.15)]:
            for q in range(n):
                a=q*2*pi/n; rad=rr*(1+random.uniform(-.15,.15)); b.v.append((cos(a)*rad,sin(a)*rad,z+level+random.uniform(-.016,.016)))
        b.f.append(tuple(k+q for q in reversed(range(n))))
        for lev in range(2):
            for q in range(n): b.f.append((k+lev*n+q,k+lev*n+(q+1)%n,k+(lev+1)*n+(q+1)%n,k+(lev+1)*n+q))
        b.f.append(tuple(k+2*n+q for q in range(n)))
    o=b.obj('Fir template '+str(variant),'04_Forest_Left'); tree_data.append(o.data); bpy.data.objects.remove(o,do_unlink=True)

for side in [-1,1]:
    group='04_Forest_Left' if side<0 else '05_Forest_Right'
    for n in range(2000):
        y=random.uniform(28,274); d=random.uniform(1.0,62); x=bank_edge(y,side)+side*d
        z=bank_z(x,y,side)
        for bounds,peaks in mountain_specs:
            if bounds[0]<x<bounds[1] and bounds[2]<y<bounds[3]: z=max(z,height_at(x,y,peaks))
        if z>22: continue
        h=random.uniform(1.8,4.6)*(1.12 if y<90 else 1)
        ob=bpy.data.objects.new(('L' if side<0 else 'R')+f'_Fir_{n:04}',random.choice(tree_data)); cols[group].objects.link(ob)
        ob.location=(x,y,z); ob.scale=(h*random.uniform(.83,1.05),h,h); ob.rotation_euler[2]=random.uniform(0,2*pi)

def rock(name,pos,scale,group):
    bpy.ops.mesh.primitive_ico_sphere_add(subdivisions=2,radius=1,location=pos)
    ob=bpy.context.object; ob.name=name
    for c in list(ob.users_collection): c.objects.unlink(ob)
    cols[group].objects.link(ob); ob.data.materials.append(mat)
    for vert in ob.data.vertices:
        vert.co*=random.uniform(.86,1.14)
    ob.scale=scale; ob.rotation_euler=(random.uniform(-.3,.3),random.uniform(-.3,.3),random.uniform(0,pi))
    bevel=ob.modifiers.new('Soft clay edges','BEVEL'); bevel.width=.08; bevel.segments=2
    for poly in ob.data.polygons: poly.use_smooth=True
    return ob

for i in range(100):
    y=random.uniform(-44,38); x=bank_edge(y,-1)+random.uniform(-6,2.1)
    r=random.uniform(.35,1.8)
    rock(f'Near shore rock {i:03}',(x,y,.2+r*.2),(r*1.5,r,r*.8),'07_Foreground_Rocks')
# Hero rocks step into the bottom-left frame.
for i,(x,y,r) in enumerate([(-11,-33,2.4),(-9,-39,2.1),(-15,-26,1.6),(-5,-43,1.8),(-17,-15,1.8)]):
    rock('Foreground hero boulder '+str(i),(x,y,.5),(r*1.25,r,r*.72),'07_Foreground_Rocks')
for side in [-1,1]:
    for i in range(75):
        y=random.uniform(25,255); x=bank_edge(y,side)+random.uniform(-.6,.7); r=random.uniform(.25,1.2)
        rock(('L' if side<0 else 'R')+f'_bank_stone_{i}',(x,y,.15),(r*1.5,r,r*.7),'03_Shore_Terrain')

for i in range(150):
    y=random.uniform(-43,12); x=bank_edge(y,-1)+random.uniform(-3.5,1)
    b=Builder(); z=max(.05,bank_z(x,y,-1))
    for blade in range(random.randint(6,11)):
        a=random.uniform(0,2*pi); h=random.uniform(.25,.85); lean=random.uniform(.12,.4)
        end=(x+cos(a)*lean,y+sin(a)*lean,z+h)
        b.tube((x,y,z),end,.018,.004,5)
        b.leaf((end[0],end[1],end[2]-.12),.32,.065,a,.9)
    b.obj(f'Grass clump {i:03}','08_Foreground_Plants',True)

# Overhanging crown is a branching tubular sculpture with individually modeled leaves.
b=Builder()
paths=[((-19,-9,15.4),(-12,-8,14.6),.25,.15),((-12,-8,14.6),(-5.5,-5,15.1),.15,.045),
       ((-17,-8,15.2),(-13,-5,11.8),.14,.045),((-13,-5,11.8),(-7.7,-4,11.4),.05,.014),
       ((-12,-8,14.6),(-10,-3,17),.1,.025)]
for a,c,r1,r2 in paths: b.tube(a,c,r1,r2,10)
for n in range(90):
    pa,pb,_,_=random.choice(paths); t=random.uniform(.1,1); anchor=Vector(pa).lerp(Vector(pb),t)
    endpoint=anchor+Vector((random.uniform(-.3,1.5),random.uniform(-1.8,1.8),random.uniform(-1.15,.65)))
    b.tube(anchor,endpoint,.026,.007,6)
    for q in range(5):
        c=anchor.lerp(endpoint,(q+1)/5)
        for side in [-1,1]:
            leafc=c+Vector((.13,side*.18,random.uniform(-.08,.08)))
            b.leaf(leafc,random.uniform(.65,.95),random.uniform(.27,.4),random.uniform(-pi,pi),random.uniform(-.45,.45))
branch=b.obj('Upper-left branch • solid leaves and tubular twigs','09_Overhanging_Branch',True)
branch.location.z=-1.8

def point(ob,at): ob.rotation_euler=(Vector(at)-ob.location).to_track_quat('-Z','Y').to_euler()
camd=bpy.data.cameras.new('Telephoto 65mm'); cam=bpy.data.objects.new('CAM • reference composition',camd); cols['10_Camera_Studio'].objects.link(cam)
cam.location=(0,-75,4.8); point(cam,(0,150,7.2)); camd.lens=65; camd.clip_end=1600; scene.camera=cam
camd.dof.use_dof=False
world=bpy.data.worlds.new('Plain white studio • no image'); world.use_nodes=True
world.node_tree.nodes['Background'].inputs[0].default_value=(1,1,1,1)
world.node_tree.nodes['Background'].inputs[1].default_value=.32; scene.world=world
wn=world.node_tree.nodes; wl=world.node_tree.links
path=wn.new('ShaderNodeLightPath'); backdrop=wn.new('ShaderNodeBackground')
backdrop.inputs[0].default_value=(1,1,1,1); backdrop.inputs[1].default_value=4
mix=wn.new('ShaderNodeMixShader')
wl.new(path.outputs['Is Camera Ray'],mix.inputs[0]); wl.new(wn['Background'].outputs[0],mix.inputs[1]); wl.new(backdrop.outputs[0],mix.inputs[2]); wl.new(mix.outputs[0],wn['World Output'].inputs['Surface'])
ld=bpy.data.lights.new('Large softbox','AREA'); lo=bpy.data.objects.new('Large softbox',ld); cols['10_Camera_Studio'].objects.link(lo)
lo.location=(-65,-10,135); ld.energy=220000; ld.shape='DISK'; ld.size=100; point(lo,(0,170,0))
ld=bpy.data.lights.new('Soft neutral sun','SUN'); lo=bpy.data.objects.new('Soft neutral sun',ld); cols['10_Camera_Studio'].objects.link(lo)
lo.rotation_euler=(math.radians(25),math.radians(-30),math.radians(-25)); ld.energy=2.0; ld.angle=math.radians(18)
scene.render.engine='CYCLES'; scene.cycles.samples=64; scene.cycles.use_denoising=True
scene.cycles.max_bounces=5
scene.render.resolution_x=1600; scene.render.resolution_y=900; scene.render.resolution_percentage=100
scene.render.image_settings.file_format='PNG'
scene.view_settings.view_transform='AgX'
scene.view_settings.exposure=.4
scene.render.film_transparent=False
scene['deliverable']='Editable 3D white clay geometry; no AI-generated image is used in the scene.'
scene['scope']='B01-B04 foundation only. Weather, seasons, animation and web integration are not implemented.'
scene['seed']=260926
for screen in bpy.data.screens:
    for area in screen.areas:
        if area.type=='VIEW_3D':
            area.spaces.active.region_3d.view_perspective='CAMERA'
            area.spaces.active.shading.type='SOLID'
            area.spaces.active.shading.light='STUDIO'
            area.spaces.active.shading.color_type='MATERIAL'
            area.spaces.active.shading.show_cavity=True
            area.spaces.active.shading.cavity_type='BOTH'
scene.render.filepath=os.path.join(OUT,'alpine-clay-preview.png')
bpy.ops.wm.save_as_mainfile(filepath=os.path.join(OUT,'alpine-lake-white-clay.blend'))
bpy.ops.render.render(write_still=True)
print('BUILD_COMPLETE',flush=True)
