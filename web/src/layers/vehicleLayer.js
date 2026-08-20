import maplibregl from "maplibre-gl";
import * as THREE from "three";
import { GLTFLoader } from "three/examples/jsm/loaders/GLTFLoader.js";

const QUALITY_COLOR = {
  GOOD: 0x2ecc71,
  DEGRADED: 0xf1c40f,
  REJECTED: 0x95a5a6,
};

// Hedef gercek dunya uzunlugu (metre) - model buna gore olceklenir.
const BUS_LENGTH = 12;
const MODEL_URL = "/models/bus/scene.gltf";
// "Isuzu Erga Mio bus" - own.guest (Sketchfab), CC-BY-4.0.
// https://sketchfab.com/3d-models/isuzu-erga-mio-bus-050e8acd0bbc4da0902a8a874ef10fca
// Atif lisans geregi zorunlu - index.html #legend alaninda gosteriliyor.

// three.js modelleri varsayilan olarak Y-up; Mercator/harita uzayi Z-up.
// Bu, resmi MapLibre/Mapbox "Three.js custom layer" ornegindeki standart
// eksen-duzeltme donusumu (model uzayinda -> harita uzayina).
const AXIS_FIX = new THREE.Matrix4().makeRotationAxis(new THREE.Vector3(1, 0, 0), Math.PI / 2);

// KALIBRASYON GECMISI: Once buraya +90 derecelik bir HEADING_OFFSET
// eklenmisti (tek bir gercek aracin egik acili bir ekran goruntusundeki
// gorsel degerlendirmeye dayanarak) - ancak izole/kontrollu bir test
// (heading=0 -> kuzeye bakan DIKEY govde beklenir, heading=90 -> doguya
// bakan YATAY govde beklenir) bu +90 offset'in aslinda YANLIS oldugunu,
// offsetsiz halin (asagida sifir) dogru oldugunu kanitladi. Onceki
// "duzeltme" muhtemelen egik acili ekran goruntusunun yanlis yorumlanmasi
// sonucuydu. Buradaki 0 deger BILINCLI - _normalizeModel'deki
// wrapper.rotation.y=-Math.PI/2 donusumu zaten modelin "on" yuzunu doju
// sekilde yerel +Z eksenine hizaliyor, heading=0 (kuzey) ile ek bir
// donusum gerekmeden dogrudan eslesiyor.
const HEADING_OFFSET = 0;

function haversineMeters(lon1, lat1, lon2, lat2) {
  const R = 6371000;
  const toRad = Math.PI / 180;
  const dLat = (lat2 - lat1) * toRad;
  const dLon = (lon2 - lon1) * toRad;
  const a =
    Math.sin(dLat / 2) ** 2 +
    Math.cos(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.sin(dLon / 2) ** 2;
  return 2 * R * Math.asin(Math.sqrt(a));
}

function bearingRadians(lon1, lat1, lon2, lat2) {
  const toRad = Math.PI / 180;
  const y = Math.sin((lon2 - lon1) * toRad) * Math.cos(lat2 * toRad);
  const x =
    Math.cos(lat1 * toRad) * Math.sin(lat2 * toRad) -
    Math.sin(lat1 * toRad) * Math.cos(lat2 * toRad) * Math.cos((lon2 - lon1) * toRad);
  return Math.atan2(y, x);
}

/**
 * MapLibre CustomLayerInterface (type:'custom', renderingMode:'3d') olarak
 * gomulu, GERCEK 3D bir Three.js katmani.
 *
 * Onceki Leaflet+Three.js versiyonunda kamera bilincli olarak duz tepeden
 * tutuluyordu (Leaflet'in kendi harita katmani hic egilemedigi icin, egik
 * bir kamera araclari yoldan "kaymis" gosterirdi). MapLibre'de bu kisit
 * yok: her render() cagrisinda haritanin KENDI o anki projeksiyon
 * matrisi (`matrix` parametresi - pan/zoom/PITCH/bearing dahil) dogrudan
 * Three.js kamerasina uygulaniyor. Yani harita gercekten egilebiliyor
 * (pitch) ve 3D katman otomatik olarak hizali kaliyor - konum hatasi
 * riski yapisal olarak ortadan kalkiyor (matrisi biz hesaplamiyoruz,
 * haritanin kendisi veriyor).
 */
export class VehicleLayer {
  constructor() {
    this.id = "vehicles-3d";
    this.type = "custom";
    this.renderingMode = "3d";
    this._vehicles = new Map(); // vehicle_id -> { group, quality, lat, lon }
    this._template = null; // GLTF yuklenince hazirlanan, normalize edilmis sablon Group
  }

  onAdd(map, gl) {
    this._map = map;
    this._camera = new THREE.Camera();
    this._scene = new THREE.Scene();
    this._scene.add(new THREE.AmbientLight(0xffffff, 0.9));
    const sun = new THREE.DirectionalLight(0xffffff, 0.8);
    sun.position.set(-1, 1.5, -0.5); // yon vektoru - directional light icin buyukluk onemsiz
    this._scene.add(sun);

    this._renderer = new THREE.WebGLRenderer({
      canvas: map.getCanvas(),
      context: gl,
      antialias: true,
    });
    this._renderer.autoClear = false;

    new GLTFLoader().load(
      MODEL_URL,
      (gltf) => {
        this._template = this._normalizeModel(gltf.scene);
      },
      undefined,
      (err) => console.error("Otobus modeli yuklenemedi, kutu-fallback kullanilacak:", err)
    );
  }

  /** Ham GLTF sahnesini: merkeze al, gercek uzunluga olcekle, "on" yonu
   * yerel +Z eksenine hizala (heading rotasyon konvansiyonumuzla eslesmesi
   * icin - bkz. _placeMesh), zemine otur (y=0 en alt nokta olsun). Boylece
   * _placeMesh'teki genel donusum TUM araclar icin ayni sekilde calisir,
   * modelin kendi orijinal koordinat sistemi onemsiz hale gelir. */
  _normalizeModel(scene) {
    const box = new THREE.Box3().setFromObject(scene);
    const size = new THREE.Vector3();
    box.getSize(size);
    const center = new THREE.Vector3();
    box.getCenter(center);

    scene.position.set(-center.x, -box.min.y, -center.z);

    const wrapper = new THREE.Group();
    wrapper.add(scene);
    // Modelin en uzun (X) ekseni -> bizim "ileri" konvansiyonumuz olan
    // +Z eksenine donduruluyor (bkz. dosya basi bounding-box analizi notu).
    wrapper.rotation.y = -Math.PI / 2;

    const scale = BUS_LENGTH / Math.max(size.x, 0.001);
    wrapper.scale.setScalar(scale);

    return wrapper;
  }

  /**
   * KRITIK HASSASIYET NOTU: Bir aracin donusum matrisini (buyuk mercator
   * translation ~0.3-0.7 + cok kucuk metre-cinsinden olcek ~1e-8) DOGRUDAN
   * group.matrix'e yazip, ayrica GPU'da (float32) haritanin projeksiyon
   * matrisiyle CARPMAK, gercek/detayli modellerde (ince govde panelleri,
   * pencere cerceveleri, ayna gibi birbirine yakin yuzeyler) siddetli
   * z-fighting/parcalanma olarak gorunuyor. Sebep: float32'nin ~7 anlamli
   * basamak hassasiyeti, translation buyuklugu (~0.4) yaninda modelin
   * kendi ic detaylarini (birbirinden sadece birkac ULP farkli) ayirt
   * edemiyor.
   *
   * Duzeltme (MapLibre/Mapbox+Three.js entegrasyonlarinda bilinen standart
   * teknik): buyuk translation + kucuk olcegi GPU'ya AYRI AYRI float32
   * matris olarak vermek yerine, HER ARAC ICIN, haritanin matrisiyle
   * aracin donusum matrisini once JS'de (float64) CARPIP tek bir kamera
   * matrisi olusturuyoruz - boylece hassasiyet kaybi carpim ONCESINDE
   * degil SONRASINDA (tek seferlik, kacinilmaz) oluyor. Bunun bedeli: artik
   * TUM sahneyi tek seferde degil, HER ARAC ICIN AYRI render() cagrisi
   * yapmamiz gerekiyor (isiklarin dogru etki etmesi icin sahne ayni kalir,
   * sadece o an render edilen arac gorunur birakilir).
   */
  render(gl, matrix) {
    const baseMatrix = new THREE.Matrix4().fromArray(matrix);
    this._renderer.resetState();

    const visibleVehicles = [];
    for (const v of this._vehicles.values()) {
      if (v.group.visible && v.localMatrix) visibleVehicles.push(v);
    }
    for (const v of visibleVehicles) v.group.visible = false;

    for (const v of visibleVehicles) {
      v.group.visible = true;
      this._camera.projectionMatrix = baseMatrix.clone().multiply(v.localMatrix);
      this._renderer.render(this._scene, this._camera);
      v.group.visible = false;
    }

    for (const v of visibleVehicles) v.group.visible = true;
    this._map.triggerRepaint(); // surekli render - replay/live pozisyon guncellemeleri aninda yansisin
  }

  _makeVehicleGroup(quality) {
    const group = new THREE.Group();

    if (this._template) {
      group.add(this._template.clone(true));
    }

    // Kalite gostergesi - gercek otobus modelinin fotogercekci dokusunu
    // yesil/sari/gri boyayip bozmak yerine, zeminde ince renkli bir halka
    // (bircok harita/filo uygulamasinin kullandigi yontem).
    const ringGeo = new THREE.RingGeometry(BUS_LENGTH * 0.3, BUS_LENGTH * 0.36, 32);
    const ringMat = new THREE.MeshBasicMaterial({
      color: QUALITY_COLOR[quality] ?? 0x3388ff,
      transparent: true, opacity: 0.85, side: THREE.DoubleSide, depthWrite: false,
    });
    const ring = new THREE.Mesh(ringGeo, ringMat);
    ring.rotation.x = -Math.PI / 2;
    ring.position.y = 0.05;
    group.add(ring);

    // Sahte zemin golgesi (performans icin gercek golge haritasi yerine
    // basit yari saydam elips, araci "yere basiyor" hissi verir).
    const shadowGeo = new THREE.CircleGeometry(1, 20);
    const shadowMat = new THREE.MeshBasicMaterial({
      color: 0x000000, transparent: true, opacity: 0.2, depthWrite: false,
    });
    const shadow = new THREE.Mesh(shadowGeo, shadowMat);
    shadow.rotation.x = -Math.PI / 2;
    shadow.scale.set(BUS_LENGTH * 0.52, BUS_LENGTH * 0.22, 1);
    shadow.position.y = 0.02;
    group.add(shadow);

    // group.matrix artik IDENTITY kalir - araci konumlandiran donusum,
    // hassasiyet nedeniyle render()'da kamera matrisine gomuluyor (bkz.
    // render() ustundeki not ve _placeMesh).
    group.userData.ring = ring;
    group.userData.heading = 0;
    group.userData.hasModel = !!this._template;
    return group;
  }

  _ensureVehicle(vehicleId, quality) {
    let v = this._vehicles.get(vehicleId);
    if (!v) {
      const group = this._makeVehicleGroup(quality);
      this._scene.add(group);
      v = { group, quality, lat: null, lon: null };
      this._vehicles.set(vehicleId, v);
    } else if (!v.group.userData.hasModel && this._template) {
      // Bu arac, model henuz yuklenmeden olusturulmustu (sayfa acilisinda
      // GLTF yuklemesi birkac yuz ms surebiliyor) - simdi hazir oldugu icin
      // gecikmeli olarak ekleniyor.
      v.group.add(this._template.clone(true));
      v.group.userData.hasModel = true;
    }
    return v;
  }

  _placeMesh(v) {
    const merc = maplibregl.MercatorCoordinate.fromLngLat([v.lon, v.lat], 0);
    const scale = merc.meterInMercatorCoordinateUnits();

    // Bu matris artik group.matrix'e degil, render()'da haritanin kendi
    // matrisiyle float64 hassasiyetinde carpilmak uzere v.localMatrix'e
    // yaziliyor (bkz. render() ustundeki hassasiyet notu).
    v.localMatrix = new THREE.Matrix4()
      .makeTranslation(merc.x, merc.y, merc.z)
      .scale(new THREE.Vector3(scale, -scale, scale))
      .multiply(AXIS_FIX)
      .multiply(new THREE.Matrix4().makeRotationY(v.group.userData.heading + HEADING_OFFSET));
  }

  /** obsByVehicle: Map(vehicle_id -> {lat, lon, map_match_quality}) o anki interpole edilmis konumlar */
  updatePositions(obsByVehicle) {
    const seen = new Set(obsByVehicle.keys());
    for (const [vehicleId, obs] of obsByVehicle) {
      const v = this._ensureVehicle(vehicleId, obs.map_match_quality);
      if (v.quality !== obs.map_match_quality) {
        v.quality = obs.map_match_quality;
        v.group.userData.ring.material.color.setHex(QUALITY_COLOR[obs.map_match_quality] ?? 0x3388ff);
      }

      v.meta = obs; // detay paneli icin (pick() ile okunuyor)
      const prevLat = v.lat;
      const prevLon = v.lon;
      v.lat = obs.lat;
      v.lon = obs.lon;
      v.group.visible = true;

      // Hareket yonune gore govdeyi dondur. obs.heading varsa (replay/live
      // controller rota-takipli interpolasyon yapiyorsa) o anki rota
      // TEGETINI dogrudan kullan - iki GPS noktasi arasindaki duz-cizgi
      // bearing'i kullansaydik, arac egri bir yol boyunca ilerlerken govde
      // sabit acida kalir, yola paralel "kayarak" gidiyormus gibi
      // gorunurdu (bkz. route-geometry.js). heading verilmemisse (rota
      // bulunamayan REJECTED/unmatched araclar) eski davranis: ardisik ham
      // konumlar arasindaki bearing.
      if (obs.heading != null) {
        v.group.userData.heading = obs.heading;
      } else if (prevLat != null && (Math.abs(prevLat - v.lat) > 1e-7 || Math.abs(prevLon - v.lon) > 1e-7)) {
        v.group.userData.heading = bearingRadians(prevLon, prevLat, v.lon, v.lat);
      }

      this._recordSpeedHistory(v, obs);
      this._placeMesh(v);
    }
    for (const [vehicleId, v] of this._vehicles) {
      if (!seen.has(vehicleId)) v.group.visible = false;
    }
    this._map?.triggerRepaint();
  }

  /** Aracin son birkac GERCEK (tekrarlanmayan observed_at) gozlemi arasindaki
   * hizi kaydeder - detay panelindeki mini hiz gecmisi (sparkline) icin.
   * Her render karesinde degil (interpolasyon araya cok sik giriyor, 60fps'te
   * anlamsiz bir gurultu birikimi olurdu) SADECE obs.observed_at bir onceki
   * kayittan FARKLI oldugunda (yani GERCEKTEN yeni bir GPS ornegine
   * gecildiginde) yeni bir nokta eklenir - dogal veri cadence'iyle (canlida
   * ~15-30sn, replay'de kayittaki gercek aralik) orantili kalir. */
  _recordSpeedHistory(v, obs) {
    if (!obs.observed_at) return;
    if (!v.speedHistory) v.speedHistory = [];
    const last = v.speedHistory[v.speedHistory.length - 1];
    if (last && last.observedAt === obs.observed_at) return;

    let speedMps = null;
    if (last) {
      const dtS = (Date.parse(obs.observed_at) - Date.parse(last.observedAt)) / 1000;
      if (dtS > 0) {
        speedMps = haversineMeters(last.lon, last.lat, obs.lon, obs.lat) / dtS;
      }
    }
    v.speedHistory.push({ observedAt: obs.observed_at, lat: obs.lat, lon: obs.lon, speedMps });
    if (v.speedHistory.length > 15) v.speedHistory.shift();
  }

  /** Bir ekran noktasina (map click event'inin e.point'i) en yakin gorunur
   * araci bulur (maxPixelDist icinde). Three.js sahnesine raycasting yerine
   * ekran-piksel mesafesi kullaniyoruz - custom layer'in projection matrisi
   * standart Three.js kamera konvansiyonlarini takip etmedigi icin (bkz.
   * render() - matrix dogrudan MapLibre'den geliyor) raycasting gereksiz
   * karmasiklik katardi; basit ve guvenilir bir yontem yeterli. */
  pick(map, point, maxPixelDist = 22) {
    let best = null;
    let bestDist = maxPixelDist;
    for (const [vehicleId, v] of this._vehicles) {
      if (!v.group.visible || v.lat == null) continue;
      const screenPt = map.project([v.lon, v.lat]);
      const dist = Math.hypot(screenPt.x - point.x, screenPt.y - point.y);
      if (dist < bestDist) {
        bestDist = dist;
        best = { vehicleId, lat: v.lat, lon: v.lon, quality: v.quality, meta: v.meta, speedHistory: v.speedHistory ?? [] };
      }
    }
    return best;
  }
}
