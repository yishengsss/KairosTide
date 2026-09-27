import * as THREE from 'three'
import { Reflector } from 'three/addons/objects/Reflector.js'

/** The reflection camera and oblique clip plane come from Three's Reflector. */
export function createLake(reflectionSize: number): Reflector {
  const lake = new Reflector(new THREE.PlaneGeometry(1600, 1600), {
    textureWidth: reflectionSize, textureHeight: reflectionSize,
    clipBias: 0.003, multisample: 0,
    shader: {
      name: 'QuietAlpineLake',
      uniforms: { color: { value: new THREE.Color('#16454c') }, tDiffuse: { value: null }, textureMatrix: { value: new THREE.Matrix4() } },
      vertexShader: `
        uniform mat4 textureMatrix; varying vec4 vUv; varying vec3 vWorld;
        void main(){
          vUv=textureMatrix*vec4(position,1.0);
          vWorld=(modelMatrix*vec4(position,1.0)).xyz;
          gl_Position=projectionMatrix*modelViewMatrix*vec4(position,1.0);
        }`,
      fragmentShader: `
        uniform sampler2D tDiffuse; uniform vec3 color;
        varying vec4 vUv; varying vec3 vWorld;
        float hash(vec2 p){return fract(sin(dot(p,vec2(127.1,311.7)))*43758.5453);}
        float noise(vec2 p){
          vec2 i=floor(p),f=fract(p);f=f*f*(3.0-2.0*f);
          return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);
        }
        void main(){
          vec2 p=vWorld.xz;
          float n=noise(p*vec2(.48,2.9));
          float fine=noise(p*vec2(1.6,9.0));
          float wave=sin(p.y*4.1+p.x*.6+n*6.0);
          vec2 normal=vec2((n-.5)*.004,(wave*.4+fine-.5)*.0013);
          vec2 uv=vUv.xy/vUv.w+normal;
          vec3 reflection=texture2D(tDiffuse,uv).rgb;
          vec3 eye=normalize(cameraPosition-vWorld);
          float fresnel=.32+.62*pow(1.0-max(eye.y,0.0),4.0);
          vec3 water=mix(color*.7,reflection,fresnel);
          water+=vec3(.06,.08,.08)*(fine-.5);
          // Broken low-intensity sheen, clipped by the actual horizontal water mesh.
          float sheen=pow(max(0.0,wave),18.0)*.028;
          water+=vec3(.75,.67,.49)*sheen;
          gl_FragColor=vec4(water,1.0);
          #include <tonemapping_fragment>
          #include <colorspace_fragment>
        }`,
    },
  })
  lake.name = '06-horizontal-lake'
  lake.rotation.x = -Math.PI / 2
  lake.position.set(0, 0, -130)
  return lake
}
