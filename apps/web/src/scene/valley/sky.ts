import * as THREE from 'three'

/** A world-space sky dome: no source photograph or screen-space colour overlay. */
export function createSky(): THREE.Mesh {
  const material = new THREE.ShaderMaterial({
    side: THREE.BackSide, depthWrite: false,
    uniforms: {
      zenith: { value: new THREE.Color('#6097bd') },
      horizon: { value: new THREE.Color('#f0d7af') },
    },
    vertexShader: `varying vec3 vWorld;
      void main() {
        vWorld = (modelMatrix * vec4(position, 1.0)).xyz;
        gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
      }`,
    fragmentShader: `
      uniform vec3 zenith; uniform vec3 horizon; varying vec3 vWorld;
      float hash(vec2 p) { return fract(sin(dot(p, vec2(127.1,311.7))) * 43758.5453); }
      float noise(vec2 p) {
        vec2 i=floor(p), f=fract(p); f=f*f*(3.0-2.0*f);
        return mix(mix(hash(i),hash(i+vec2(1,0)),f.x),mix(hash(i+vec2(0,1)),hash(i+vec2(1,1)),f.x),f.y);
      }
      float fbm(vec2 p) {
        float n=0.0, a=.5;
        for(int i=0;i<5;i++){n+=noise(p)*a; p=p*2.03+vec2(7.3,1.2); a*=.5;}
        return n;
      }
      void main() {
        vec3 direction=normalize(vWorld-cameraPosition);
        float height=max(0.0,direction.y);
        vec3 c=mix(horizon,zenith,pow(clamp(height*2.0,0.0,1.0),.48));
        vec3 sunDirection=normalize(vec3(-.27,.10,-1.0));
        float glow=pow(max(0.0,dot(direction,sunDirection)),38.0);
        c+=vec3(.3,.13,.025)*glow;
        // Static wisps in three depth/frequency bands. Weather animation comes later.
        vec2 p=direction.xz/max(.12,height)*1.6;
        float clouds=smoothstep(.53,.79,fbm(p*2.1))*.34;
        clouds+=smoothstep(.64,.85,fbm(p*.9+31.0))*.24;
        clouds*=smoothstep(.015,.09,height)*(1.0-smoothstep(.32,.7,height));
        c=mix(c,vec3(.86,.81,.73),clouds);
        gl_FragColor=vec4(c,1.0);
        #include <tonemapping_fragment>
        #include <colorspace_fragment>
      }`,
  })
  const sky = new THREE.Mesh(new THREE.SphereGeometry(650, 40, 20), material)
  sky.name = '00-sky-dome'
  sky.renderOrder = -10
  return sky
}
