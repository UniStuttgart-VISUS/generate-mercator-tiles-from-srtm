const map = L.map('map', {
  renderer: L.canvas(),
  worldCopyJump: true,
}).setView([56, -3], 9);

const lowTileLayer = L.tileLayer('/tiles/{z}/{x}/{y}.png', {
  attribution: 'Map data &copy; 2024 <a href="https://darus.uni-stuttgart.de/dataset.xhtml?persistentId=doi:10.18419/darus-3837" target="_blank">Max Franke</a>',
  maxNativeZoom: 6,
});
const highTileLayer = L.tileLayer('/tiles/{z}/{x}/{y}.png', {
  minZoom: 7,
  maxNativeZoom: 12,
});


const tileGroup = L.layerGroup([lowTileLayer, highTileLayer]);

tileGroup.addTo(map);
const layerControl = L.control.layers({}, {tileGroup}, {collapsed: false});
layerControl.addTo(map);


// GeoJSON data
const req = await fetch('../features.geo.json');
const data = await req.json();

const { type, crs, features } = data;

const areas = {
  type, crs,
  features: features.filter(v => v.geometry.type === 'Polygon' || v.geometry.type === 'MultiPolygon'),
};
const lines = {
  type, crs,
  features: features.filter(v => v.geometry.type === 'LineString' || v.geometry.type === 'MultiLineString'),
};

const lineLayer = L.geoJSON(lines, {
  style: {
    stroke: true,
    fill: false,
    color: 'steelblue',
    weight: 2,
  }
});
const areaLayer = L.geoJSON(areas, {
  style: {
    stroke: false,
    fill: true,
    fillColor: 'steelblue',
    fillOpacity: 1,
  }
});
const geoJsonGroup = L.layerGroup([lineLayer, areaLayer]);
layerControl.addOverlay(geoJsonGroup, 'NaturalEarth')


const d = new L.Control({position: 'bottomleft'});
d.onZoom = function(e) {
  this.span.innerHTML = `Zoom level: ${map.getZoom()}`;
}
d._onzoom = d.onZoom.bind(d);
d.onAdd = function(map) {
  map.on('zoom', this._onzoom);
  const div = L.DomUtil.create('div', 'leaflet-control-layers zoom-display');
  const span = L.DomUtil.create('span', null, div);
  this.span = span;
  span.innerHTML = `Zoom level: ${map.getZoom()}`;
  return div;
}
d.onRemove = function(map) {
  map.off('zoom', this._onzoom);
}
console.log(d, d instanceof L.Control)
d.addTo(map);