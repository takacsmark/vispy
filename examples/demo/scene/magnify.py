# -*- coding: utf-8 -*-
# Copyright (c) 2014, Vispy Development Team.
# Distributed under the (new) BSD License. See LICENSE.txt for more info.

"""
"""

import numpy as np
import vispy.scene
from vispy import gloo, app
from vispy.scene import visuals
from vispy.scene.transforms import (STTransform, BaseTransform, arg_to_vec4, 
                                    as_vec4)
from vispy.util import filter 


class MagnifyTransform(BaseTransform):
    """
    """
    glsl_map = """
        vec4 mag_transform(vec4 pos) {
            vec2 d = vec2(pos.x - $center.x, pos.y - $center.y);
            float dist = length(d);
            if (dist == 0 || dist > $radii.y || $mag == 1) {
                return pos;
            }
            vec2 dir = d / dist;
            
            if( dist < $radii.x ) {
                dist = dist * $mag;
            }
            else {
                
                float r1 = $radii.x;
                float r2 = $radii.y;
                float x = (dist - r1) / (r2 - r1);
                float s = texture2D($trans, vec2(0, x)).r * $trans_max;
                
                dist = s;
            }

            d = $center + dir * dist;
            return vec4(d, pos.z, pos.w);
        }"""
    
    glsl_imap = glsl_map
    
    Linear = False
    
    _trans_resolution = 1000
    
    def __init__(self):
        self._center = (0, 0)
        self._mag = 5
        self._radii = (7, 10)
        self._trans = None
        res = self._trans_resolution
        self._trans_tex = (gloo.Texture2D(shape=(res, 1, 1), 
                                          format=gloo.gl.GL_LUMINANCE, 
                                          dtype=np.float32, 
                                          interpolation='linear'), 
                           gloo.Texture2D(shape=(res, 1, 1), 
                                          format=gloo.gl.GL_LUMINANCE, 
                                          dtype=np.float32, 
                                          interpolation='linear'))
        self._trans_tex_max = None
        super(MagnifyTransform, self).__init__()
        
    @property
    def center(self):
        return self._center
    
    @center.setter
    def center(self, center):
        if np.allclose(self._center, center):
            return
        self._center = center
        self.shader_map()
        self.shader_imap()

    @property
    def magnification(self):
        return self._mag
    
    @magnification.setter
    def magnification(self, mag):
        if self._mag == mag:
            return
        self._mag = mag
        self._trans = None
        self.shader_map()
        self.shader_imap()

    @property
    def radii(self):
        return self._radii
    
    @radii.setter
    def radii(self, radii):
        if np.allclose(self._radii, radii):
            return
        self._radii = radii
        self._trans = None
        self.shader_map()
        self.shader_imap()

    def shader_map(self):
        fn = super(MagnifyTransform, self).shader_map()
        fn['center'] = self._center  # uniform vec2
        fn['mag'] = self._mag
        fn['radii'] = (self._radii[0] / self._mag, self._radii[1])
        self._get_transition()  # make sure transition texture is up to date
        fn['trans'] = self._trans_tex[0]
        fn['trans_max'] = self._trans_tex_max[0]
        return fn

    def shader_imap(self):
        fn = super(MagnifyTransform, self).shader_imap()
        fn['center'] = self._center  # uniform vec2
        fn['mag'] = 1. / self._mag
        fn['radii'] = self._radii
        self._get_transition()  # make sure transition texture is up to date
        fn['trans'] = self._trans_tex[1]
        fn['trans_max'] = self._trans_tex_max[1]
        return fn

    @arg_to_vec4
    def map(self, x, _inverse=False):
        c = as_vec4(self.center)
        m = self.magnification
        r1, r2 = self.radii
        
        #c = np.array(c).reshape(1,2)
        xm = np.empty(x.shape, dtype=x.dtype)
        
        dx = (x - c)
        dist = (((dx**2).sum(axis=-1)) ** 0.5)[..., np.newaxis]
        dist[np.isnan(dist)] = 0
        unit = dx / dist
        
        # magnified center region
        if _inverse:
            inner = (dist < r1)[:, 0]
            s = dist / m
        else:
            inner = (dist < (r1 / m))[:, 0]
            s = dist * m
        xm[inner] = c + unit[inner] * s[inner]
        
        # unmagnified outer region
        outer = (dist > r2)[:, 0]  
        xm[outer] = x[outer]
        
        # smooth transition region, interpolated from trans
        trans = ~(inner | outer)

        # look up scale factor from trans
        temp, itemp = self._get_transition()
        if _inverse:
            tind = (dist[trans] - r1) * len(itemp) / (r2 - r1)
            temp = itemp
        else:
            tind = (dist[trans] - (r1/m)) * len(temp) / (r2 - (r1/m))
        tind = np.clip(tind, 0, temp.shape[0]-1)
        s = temp[tind.astype(int)]
        
        xm[trans] = c + unit[trans] * s
        return xm

    def imap(self, coords):
        return self.map(coords, _inverse=True)

    def _get_transition(self):
        # Generate forward/reverse transition templates.
        # We would prefer to express this with an invertible function, but that
        # turns out to be tricky. The trans makes any function invertible.
        
        if self._trans is None:
            m, r1, r2 = self.magnification, self.radii[0], self.radii[1]
            res = self._trans_resolution
            
            xi = np.linspace(r1, r2, res)
            t = 0.5 * (1 + np.cos((xi - r2) * np.pi / (r2 - r1)))
            yi = (xi * t + xi * (1-t) / m).astype(np.float32)
            x = np.linspace(r1 / m, r2, res)
            y = np.interp(x, yi, xi).astype(np.float32)
            
            self._trans = (y, yi)
            # scale to 0.0-1.0 to prevent clipping (is this necessary?)
            mx = y.max(), yi.max()
            self._trans_tex_max = mx
            self._trans_tex[0].set_data((y/mx[0])[:, np.newaxis, np.newaxis])
            self._trans_tex[1].set_data((yi/mx[1])[:, np.newaxis, np.newaxis])
            
        return self._trans


class Magnify1DTransform(MagnifyTransform):
    """
    """
    glsl_map = """
        vec4 mag_transform(vec4 pos) {
            float dist = pos.x - $center.x;
            if (dist == 0 || abs(dist) > $radii.y || $mag == 1) {
                return pos;
            }
            float dir = dist / abs(dist);
            
            if( abs(dist) < $radii.x ) {
                dist = dist * $mag;
            }
            else {
                float r1 = $radii.x;
                float r2 = $radii.y;
                float x = (abs(dist) - r1) / (r2 - r1);
                dist = dir * texture2D($trans, vec2(0, x)).r * $trans_max;
            }

            return vec4($center.x + dist, pos.y, pos.z, pos.w);
        }"""
    
    glsl_imap = glsl_map


class MagCamera(vispy.scene.cameras.PanZoomCamera):
    def __init__(self, *args, **kwds):
        self.mag = MagnifyTransform()
        self.mag_target = 3
        self.mag._mag = self.mag_target
        self.mouse_pos = None
        self.timer = app.Timer(interval=0.016, connect=self.on_timer)
        super(MagCamera, self).__init__(*args, **kwds)

    def view_mouse_event(self, event):
        self.mouse_pos = event.pos[:2]
        if event.type == 'mouse_wheel':
            m = self.mag_target 
            m *= 1.2 ** event.delta[1]
            m = m if m > 1 else 1
            self.mag_target = m
        else:
            super(MagCamera, self).view_mouse_event(event)
        self.on_timer()
        self.timer.start()
        self._update_transform()
    
    def on_timer(self, event=None):
        c = np.array(self.mag.center)
        if event is None:
            dt = 0.001
        else:
            dt = event.dt
        s = 0.0001**dt
        c1 = c * s + self.mouse_pos * (1-s)
        
        m = self.mag.magnification * s + self.mag_target * (1-s)
        
        if (np.all(np.abs((c - c1) / c1) < 1e-5) and 
            (np.abs(np.log(m / self.mag.magnification)) < 1e-3)):
            self.timer.stop()
            
        self.mag.center = c1
        self.mag.magnification = m
            
        self._update_transform()
    
    def _set_scene_transform(self, tr):
        vbs = self.viewbox.size
        r = min(vbs) / 2
        self.mag.radii = r*0.7, r
        super(MagCamera, self)._set_scene_transform(self.mag * tr)


class Mag1DCamera(MagCamera):
    def __init__(self, *args, **kwds):
        super(Mag1DCamera, self).__init__(*args, **kwds)
        self.mag = Magnify1DTransform()
        self.mag._mag = 3

    def _set_scene_transform(self, tr):
        vbs = self.viewbox.size
        r = vbs[0] / 4
        self.mag.radii = r*0.7, r 
        super(MagCamera, self)._set_scene_transform(self.mag * tr)


canvas = vispy.scene.SceneCanvas(keys='interactive', show=True)
grid = canvas.central_widget.add_grid()

vb1 = grid.add_view(row=0, col=0, col_span=2)
vb2 = grid.add_view(row=1, col=0)
vb3 = grid.add_view(row=1, col=1)

# Top viewbox
vb1.camera = Mag1DCamera()
pos = np.empty((100000, 2))
pos[:, 0] = np.arange(100000)
pos[:, 1] = np.random.normal(size=100000, loc=50, scale=10)
pos[:, 1] = filter.gaussian_filter(pos[:, 1], 20)
pos[:, 1] += np.random.normal(size=100000, loc=0, scale=2)
pos[:, 1][pos[:, 1] > 55] += 100
pos[:, 1] = filter.gaussian_filter(pos[:, 1], 2)
line = visuals.Line(pos, color='white', parent=vb1.scene)
line.transform = STTransform(translate=(0, 0, -0.1))
vb1.camera.rect = 0, 30, 100000, 100

grid1 = visuals.GridLines(parent=vb1.scene)


#
# bottom-left viewbox
#
img_data = np.random.normal(size=(100, 100, 3), loc=58,
                            scale=20).astype(np.ubyte)

image = visuals.Image(img_data, method='impostor', grid=(100, 100), 
                      parent=vb2.scene)
vb2.camera = MagCamera()
vb2.camera.rect = (-10, -10, image.size[0]+20, image.size[1]+20) 


#
# bottom-right viewbox
#
centers = np.random.normal(size=(20, 2))
pos = np.random.normal(size=(100000, 2), scale=0.2)

indexes = np.random.normal(size=100000, loc=centers.shape[0]/2., 
                           scale=centers.shape[0]/3.)
indexes = np.clip(indexes, 0, centers.shape[0]-1).astype(int)
scales = np.linspace(0.1, 1, centers.shape[0])[indexes][:, np.newaxis]

pos *= scales
pos += centers[indexes]

vb3.camera = MagCamera()
scatter = visuals.Markers()
scatter.set_data(pos, edge_color=None, face_color=(1, 1, 1, 0.3), size=5)
vb3.add(scatter)
vb3.camera.rect = (-5, -5, 10, 10)
grid2 = visuals.GridLines(parent=vb3.scene)

text = visuals.Text("mouse wheel = zoom", pos=(100, 15), font_size=14, 
                    color='white', parent=canvas.scene)


if __name__ == '__main__':
    import sys
    if sys.flags.interactive != 1:
        vispy.app.run()
