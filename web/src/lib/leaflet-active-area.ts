// Vendored from leaflet-active-area@1.3.1 with a MaptilerLayer patch.
// Original: https://github.com/Mappy/Leaflet-active-area
//
// MaptilerLayer extends L.Layer (not L.GridLayer) and calls getCenter() /
// getBounds() expecting container coordinates, so it needs its own patch.
//
// This file monkey-patches Leaflet prototypes via .include(), accessing many
// private internals (_viewport, _zoom, _move, etc.) that have no public types.
/* eslint-disable @typescript-eslint/no-explicit-any, @typescript-eslint/no-unsafe-function-type, @typescript-eslint/no-this-alias */

import L from "leaflet";
import { MaptilerLayer } from "@maptiler/leaflet-maptilersdk";

declare module "leaflet" {
  interface Map {
    setActiveArea(
      cssClassOrStyles: string | Partial<CSSStyleDeclaration>,
      keepCenter?: boolean,
      animate?: boolean,
    ): this;
    getViewport(): HTMLDivElement | undefined;
    getViewportBounds(): L.Bounds;
    getViewportLatLngBounds(): L.LatLngBounds;
    getOffset(): L.Point;
    getCenter(withoutViewport?: boolean): L.LatLng;
  }
}

const previousMethods = {
  getCenter: L.Map.prototype.getCenter,
  setView: L.Map.prototype.setView,
  flyTo: L.Map.prototype.flyTo,
  setZoomAround: L.Map.prototype.setZoomAround,
  getBoundsZoom: L.Map.prototype.getBoundsZoom,
  PopupAdjustPan: (L.Popup.prototype as any)._adjustPan as Function,
  RendererUpdate: (L.Renderer.prototype as any)._update as Function,
};

L.Map.include({
  getBounds(this: any) {
    if (this._viewport) {
      return this.getViewportLatLngBounds();
    }
    const bounds = this.getPixelBounds();
    const sw = this.unproject(bounds.getBottomLeft());
    const ne = this.unproject(bounds.getTopRight());
    return new L.LatLngBounds(sw, ne);
  },

  getViewport(this: any): HTMLDivElement | undefined {
    return this._viewport;
  },

  getViewportBounds(this: any): L.Bounds {
    let vp: HTMLElement = this._viewport;
    let topleft = L.point(vp.offsetLeft, vp.offsetTop);
    let vpsize = L.point(vp.clientWidth, vp.clientHeight);

    if (vpsize.x === 0 || vpsize.y === 0) {
      vp = this.getContainer();
      if (vp) {
        topleft = L.point(0, 0);
        vpsize = L.point(vp.clientWidth, vp.clientHeight);
      }
    }

    return L.bounds(topleft, topleft.add(vpsize));
  },

  getViewportLatLngBounds(this: any): L.LatLngBounds {
    const bounds = this.getViewportBounds();
    return L.latLngBounds(
      this.containerPointToLatLng(bounds.min),
      this.containerPointToLatLng(bounds.max),
    );
  },

  getOffset(this: any): L.Point {
    const mCenter = this.getSize().divideBy(2);
    const vCenter = this.getViewportBounds().getCenter();
    return mCenter.subtract(vCenter);
  },

  getCenter(this: any, withoutViewport?: boolean): L.LatLng {
    let center: L.LatLng = previousMethods.getCenter.call(this);

    if (this.getViewport() && !withoutViewport) {
      const zoom = this.getZoom();
      let point = this.project(center, zoom);
      point = point.subtract(this.getOffset());
      center = this.unproject(point, zoom);
    }

    return center;
  },

  setView(this: any, center: any, zoom: any, options: any) {
    center = L.latLng(center);
    zoom = zoom === undefined ? this._zoom : this._limitZoom(zoom);

    if (this.getViewport()) {
      let point = this.project(center, this._limitZoom(zoom));
      point = point.add(this.getOffset());
      center = this.unproject(point, this._limitZoom(zoom));
    }

    return previousMethods.setView.call(this, center, zoom, options);
  },

  flyTo(this: any, targetCenter: any, targetZoom: any, options: any) {
    targetCenter = L.latLng(targetCenter);

    if (this.getViewport()) {
      let point = this.project(
        targetCenter,
        this._limitZoom(targetZoom),
      );
      point = point.add(this.getOffset());
      targetCenter = this.unproject(point, this._limitZoom(targetZoom));
    }

    options = options || {};
    if (options.animate === false || !L.Browser.any3d) {
      return this.setView(targetCenter, targetZoom, options);
    }

    this._stop();

    const from = this.project(previousMethods.getCenter.call(this));
    const to = this.project(targetCenter);
    const size = this.getSize();
    const startZoom = this._zoom;

    targetZoom = targetZoom === undefined ? startZoom : targetZoom;

    const w0 = Math.max(size.x, size.y);
    const w1 = w0 * this.getZoomScale(startZoom, targetZoom);
    const u1 = to.distanceTo(from) || 1;
    const rho = 1.42;
    const rho2 = rho * rho;

    function r(i: number) {
      const s1 = i ? -1 : 1;
      const s2 = i ? w1 : w0;
      const t1 = w1 * w1 - w0 * w0 + s1 * rho2 * rho2 * u1 * u1;
      const b1 = 2 * s2 * rho2 * u1;
      const b = t1 / b1;
      const sq = Math.sqrt(b * b + 1) - b;
      return sq < 0.000000001 ? -18 : Math.log(sq);
    }

    function sinh(n: number) {
      return (Math.exp(n) - Math.exp(-n)) / 2;
    }
    function cosh(n: number) {
      return (Math.exp(n) + Math.exp(-n)) / 2;
    }
    function tanh(n: number) {
      return sinh(n) / cosh(n);
    }

    const r0 = r(0);

    function w(s: number) {
      return w0 * (cosh(r0) / cosh(r0 + rho * s));
    }
    function u(s: number) {
      return (w0 * (cosh(r0) * tanh(r0 + rho * s) - sinh(r0))) / rho2;
    }

    function easeOut(t: number) {
      return 1 - Math.pow(1 - t, 1.5);
    }

    const start = Date.now();
    const S = (r(1) - r0) / rho;
    const duration = options.duration ? 1000 * options.duration : 1000 * S * 0.8;

    const self = this;
    function frame() {
      const t = (Date.now() - start) / duration;
      const s = easeOut(t) * S;

      if (t <= 1) {
        self._flyToFrame = L.Util.requestAnimFrame(frame, self);
        self._move(
          self.unproject(
            from.add(to.subtract(from).multiplyBy(u(s) / u1)),
            startZoom,
          ),
          self.getScaleZoom(w0 / w(s), startZoom),
          { flyTo: true },
        );
      } else {
        self._move(targetCenter, targetZoom)._moveEnd(true);
      }
    }

    this._moveStart(true, options.noMoveStart);
    frame();
    return this;
  },

  setZoomAround(this: any, latlng: any, zoom: number, options: any) {
    const vp = this.getViewport();

    if (vp) {
      const scale = this.getZoomScale(zoom);
      const viewHalf = this.getViewportBounds().getCenter();
      const containerPoint =
        latlng instanceof L.Point
          ? latlng
          : this.latLngToContainerPoint(latlng);
      const centerOffset = containerPoint
        .subtract(viewHalf)
        .multiplyBy(1 - 1 / scale);
      const newCenter = this.containerPointToLatLng(
        viewHalf.add(centerOffset),
      );
      return this.setView(newCenter, zoom, { zoom: options });
    }
    return previousMethods.setZoomAround.call(this, latlng, zoom, options);
  },

  getBoundsZoom(this: any, bounds: any, inside: boolean, padding: any) {
    bounds = L.latLngBounds(bounds);
    padding = L.point(padding || [0, 0]);

    let zoom = this.getZoom() || 0;
    const min = this.getMinZoom();
    const max = this.getMaxZoom();
    const nw = bounds.getNorthWest();
    const se = bounds.getSouthEast();
    const vp = this.getViewport();
    const size = (
      vp
        ? L.point(vp.clientWidth, vp.clientHeight)
        : this.getSize()
    ).subtract(padding);
    const boundsSize = this.project(se, zoom).subtract(this.project(nw, zoom));
    const snap = L.Browser.any3d ? this.options.zoomSnap : 1;
    const scalex = size.x / boundsSize.x;
    const scaley = size.y / boundsSize.y;
    const scale = inside
      ? Math.max(scalex, scaley)
      : Math.min(scalex, scaley);

    zoom = this.getScaleZoom(scale, zoom);

    if (snap) {
      zoom = Math.round(zoom / (snap / 100)) * (snap / 100);
      zoom = inside
        ? Math.ceil(zoom / snap) * snap
        : Math.floor(zoom / snap) * snap;
    }

    return Math.max(min, Math.min(max, zoom));
  },

  setActiveArea(
    this: any,
    css: string | Partial<CSSStyleDeclaration>,
    keepCenter?: boolean,
    animate?: boolean,
  ) {
    let center: L.LatLng | undefined;
    if (keepCenter && this._zoom) {
      center = this.getCenter();
    }

    if (!this._viewport) {
      const container = this.getContainer();
      this._viewport = L.DomUtil.create("div", "");
      container.insertBefore(this._viewport, container.firstChild);
    }

    if (typeof css === "string") {
      this._viewport.className = css;
    } else {
      L.extend(this._viewport.style, css);
    }

    if (center) {
      this.setView(center, this.getZoom(), { animate: !!animate });
    }
    return this;
  },
});

L.Renderer.include({
  _onZoom(this: any) {
    this._updateTransform(this._map.getCenter(true), this._map.getZoom());
  },

  _update(this: any) {
    previousMethods.RendererUpdate.call(this);
    this._center = this._map.getCenter(true);
  },
});


L.GridLayer.include({
  _updateLevels(this: any) {
    const zoom = this._tileZoom;
    const maxZoom = this.options.maxZoom;

    if (zoom === undefined) {
      return undefined;
    }

    for (const z in this._levels) {
      const zNum = Number(z);
      if (this._levels[zNum].el.children.length || zNum === zoom) {
        this._levels[zNum].el.style.zIndex = maxZoom - Math.abs(zoom - zNum);
        this._onUpdateLevel(zNum);
      } else {
        L.DomUtil.remove(this._levels[zNum].el);
        this._removeTilesAtZoom(zNum);
        this._onRemoveLevel(zNum);
        delete this._levels[zNum];
      }
    }

    const map = this._map;
    let level = this._levels[zoom];

    if (!level) {
      level = this._levels[zoom] = {} as any;

      level.el = L.DomUtil.create(
        "div",
        "leaflet-tile-container leaflet-zoom-animated",
        this._container,
      );
      level.el.style.zIndex = maxZoom;

      level.origin = map
        .project(map.unproject(map.getPixelOrigin()), zoom)
        .round();
      level.zoom = zoom;

      this._setZoomTransform(level, map.getCenter(true), map.getZoom());

      (L.Util.falseFn as any)(level.el.offsetWidth);

      this._onCreateLevel(level);
    }

    this._level = level;

    return level;
  },

  _resetView(this: any, e: any) {
    const animating = e && (e.pinch || e.flyTo);
    this._setView(
      this._map.getCenter(true),
      this._map.getZoom(),
      animating,
      animating,
    );
  },

  _update(this: any, center: any) {
    const map = this._map;
    if (!map) {
      return;
    }
    const zoom = this._clampZoom(map.getZoom());

    if (center === undefined) {
      center = map.getCenter(true);
    }
    if (this._tileZoom === undefined) {
      return;
    }

    const pixelBounds = this._getTiledPixelBounds(center);
    const tileRange = this._pxBoundsToTileRange(pixelBounds);
    const tileCenter = tileRange.getCenter();
    const queue: any[] = [];
    const margin = this.options.keepBuffer;
    const noPruneRange = new L.Bounds(
      tileRange.getBottomLeft().subtract([margin, -margin]),
      tileRange.getTopRight().add([margin, -margin]),
    );

    if (
      !(
        isFinite(tileRange.min.x) &&
        isFinite(tileRange.min.y) &&
        isFinite(tileRange.max.x) &&
        isFinite(tileRange.max.y)
      )
    ) {
      throw new Error("Attempted to load an infinite number of tiles");
    }

    for (const key in this._tiles) {
      const c = this._tiles[key].coords;
      if (
        c.z !== this._tileZoom ||
        !noPruneRange.contains(new L.Point(c.x, c.y))
      ) {
        this._tiles[key].current = false;
      }
    }

    if (Math.abs(zoom - this._tileZoom) > 1) {
      this._setView(center, zoom);
      return;
    }

    for (let j = tileRange.min.y; j <= tileRange.max.y; j++) {
      for (let i = tileRange.min.x; i <= tileRange.max.x; i++) {
        const coords = new L.Point(i, j) as any;
        coords.z = this._tileZoom;

        if (!this._isValidTile(coords)) {
          continue;
        }

        const tile = this._tiles[this._tileCoordsToKey(coords)];
        if (tile) {
          tile.current = true;
        } else {
          queue.push(coords);
        }
      }
    }

    queue.sort((a: any, b: any) => {
      return a.distanceTo(tileCenter) - b.distanceTo(tileCenter);
    });

    if (queue.length !== 0) {
      if (!this._loading) {
        this._loading = true;
        this.fire("loading");
      }

      const fragment = document.createDocumentFragment();

      for (let i = 0; i < queue.length; i++) {
        this._addTile(queue[i], fragment);
      }

      this._level.el.appendChild(fragment);
    }
  },
});

// MaptilerLayer extends L.Layer (not L.GridLayer), so it has its own
// _transformGL / _animateZoom / _pinchZoom / _transitionEnd that call
// map.getCenter() and map.getBounds(). With active-area, those return
// viewport-relative values, but MaptilerLayer positions a WebGL canvas
// in container coordinates. We patch to use getCenter(true) and compute
// container bounds directly so the tile canvas stays in sync.
{
  const proto = MaptilerLayer.prototype as any;

  // Helper: get container bounds (bypasses viewport-aware getBounds)
  function getContainerBounds(map: any): L.LatLngBounds {
    const bounds = map.getPixelBounds();
    const sw = map.unproject(bounds.getBottomLeft());
    const ne = map.unproject(bounds.getTopRight());
    return new L.LatLngBounds(sw, ne);
  }

  proto._transformGL = function (this: any) {
    if (!this._maptilerMap) return;
    this._maptilerMap.setCenter(this._map.getCenter(true));
    this._maptilerMap.setZoom(this._map.getZoom() - 1);
  };

  proto._pinchZoom = function (this: any) {
    if (!this._maptilerMap) return;
    this._maptilerMap.jumpTo({
      zoom: this._map.getZoom() - 1,
      center: this._map.getCenter(true),
    });
  };

  proto._animateZoom = function (this: any, t: any) {
    if (!this._maptilerMap) return;
    const map = this._map;
    const scale = map.getZoomScale(t.zoom);
    const padded = map.getSize().multiplyBy(this.options.padding * scale);
    const halfSize = this.getSize()._divideBy(2);
    const origin = map
      .project(t.center, t.zoom)
      ._subtract(halfSize)
      ._add(map._getMapPanePos().add(padded))
      ._round();
    const nw = getContainerBounds(map).getNorthWest();
    const p = map.project(nw, t.zoom)._subtract(origin);
    L.DomUtil.setTransform(
      this._maptilerMap.getCanvas(),
      p.subtract(this._offset),
      scale,
    );
  };

  proto._transitionEnd = function (this: any) {
    if (!this._maptilerMap) return;
    L.Util.requestAnimFrame(() => {
      const zoom = this._map.getZoom();
      const nw = getContainerBounds(this._map).getNorthWest();
      const o = this._map.latLngToContainerPoint(nw);
      L.DomUtil.setTransform(this._maptilerMap._actualCanvas, o, 1);
      this._maptilerMap.once(
        "moveend",
        L.Util.bind(() => {
          this._zoomEnd();
        }, this),
      );
      this._maptilerMap.jumpTo({
        center: this._map.getCenter(true),
        zoom: zoom - 1,
      });
    }, this);
  };
}

L.Popup.include({
  _adjustPan(this: any) {
    if (!this._map._viewport) {
      previousMethods.PopupAdjustPan.call(this);
    } else {
      if (!this.options.autoPan) {
        return;
      }
      if (this._map._panAnim) {
        this._map._panAnim.stop();
      }

      const map = this._map;
      const vp = map._viewport as HTMLElement;
      const containerHeight = this._container.offsetHeight;
      const containerWidth = this._containerWidth;
      const vpTopleft = L.point(vp.offsetLeft, vp.offsetTop);
      let layerPos = new L.Point(
        this._containerLeft - vpTopleft.x,
        -containerHeight - this._containerBottom - vpTopleft.y,
      );

      layerPos = layerPos.add(L.DomUtil.getPosition(this._container));

      const containerPos = map.layerPointToContainerPoint(layerPos);
      const padding = L.point(this.options.autoPanPadding);
      const paddingTL = L.point(
        this.options.autoPanPaddingTopLeft || padding,
      );
      const paddingBR = L.point(
        this.options.autoPanPaddingBottomRight || padding,
      );
      const size = L.point(vp.clientWidth, vp.clientHeight);
      let dx = 0;
      let dy = 0;

      if (containerPos.x + containerWidth + paddingBR.x > size.x) {
        dx = containerPos.x + containerWidth - size.x + paddingBR.x;
      }
      if (containerPos.x - dx - paddingTL.x < 0) {
        dx = containerPos.x - paddingTL.x;
      }
      if (containerPos.y + containerHeight + paddingBR.y > size.y) {
        dy = containerPos.y + containerHeight - size.y + paddingBR.y;
      }
      if (containerPos.y - dy - paddingTL.y < 0) {
        dy = containerPos.y - paddingTL.y;
      }

      if (dx || dy) {
        map.fire("autopanstart").panBy([dx, dy]);
      }
    }
  },
});
