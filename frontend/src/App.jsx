import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Activity, ArrowDown, ArrowRight, ArrowUpRight, Building2, Check, ChevronRight,
  CircleAlert, Clock3, Construction, Droplets, Globe2, Leaf, Lightbulb, LogOut,
  MapPin, MapPinned, ShieldCheck, Sparkles, Trash2, UserRound,
} from "lucide-react";
import {
  Circle, CircleMarker, MapContainer, Popup, TileLayer, useMap, useMapEvents,
} from "react-leaflet";
import "leaflet/dist/leaflet.css";
import "./App.css";
import { refreshCsrf, request } from "./api";
import heroImage from "./assets/nodal-bengaluru-hero.png";

const CATEGORIES = [
  ["pothole", "Road damage"], ["garbage", "Waste and cleanliness"],
  ["waterlogging", "Waterlogging"], ["streetlight", "Street lighting"],
  ["water_leak", "Water leakage"], ["damaged_infrastructure", "Damaged infrastructure"],
  ["other", "Something else"],
];
const ADMIN_CATEGORIES = [...CATEGORIES, ["drainage", "Drainage"], ["unclassified", "Unclassified"]];
const PRIORITY_COLORS = { high: "#bb5235", medium: "#b99336", low: "#5d785f" };
const MAP_CITIES = [
  { id: "bengaluru", name: "Bengaluru", center: [12.9716, 77.5946], zoom: 11 },
  { id: "chennai", name: "Chennai", center: [13.0827, 80.2707], zoom: 11 },
  { id: "hyderabad", name: "Hyderabad", center: [17.385, 78.4867], zoom: 11 },
  { id: "mumbai", name: "Mumbai", center: [19.076, 72.8777], zoom: 11 },
  { id: "pune", name: "Pune", center: [18.5204, 73.8567], zoom: 11 },
  { id: "delhi", name: "Delhi", center: [28.6139, 77.209], zoom: 10 },
  { id: "kolkata", name: "Kolkata", center: [22.5726, 88.3639], zoom: 11 },
];
const SYNTHETIC_MARKER = /\[SYNTHETIC NODAL SHOWCASE\s*-\s*NOT A VERIFIED CIVIC REPORT\]/i;
const FIXTURE_MARKER = /\[fixture:[^\]]+\]/i;

function cleanSyntheticText(value) {
  return String(value || "")
    .replace(/\[SYNTHETIC NODAL SHOWCASE\s*-\s*NOT A VERIFIED CIVIC REPORT\]/gi, " ")
    .replace(/\[fixture:[^\]]+\]/gi, " ")
    .replace(/\s+/g, " ")
    .replace(/^[\s:|.,/-]+|[\s:|.,/-]+$/g, "")
    .trim();
}
function isDemoComplaint(complaint) {
  const text = `${complaint?.title || ""} ${complaint?.description || ""}`;
  return complaint?.data_quality === "demo_sample_unverified" || SYNTHETIC_MARKER.test(text) || FIXTURE_MARKER.test(text);
}

function complaintDescription(complaint) {
  return cleanSyntheticText(complaint?.description) || "Description not available.";
}

function validLatLng(lat, lng) {
  return Number.isFinite(lat) && Number.isFinite(lng) && lat >= -90 && lat <= 90 && lng >= -180 && lng <= 180;
}

function complaintLatLng(complaint) {
  const coordinates = complaint.location?.coordinates;
  if (!Array.isArray(coordinates) || coordinates.length !== 2) return null;
  const [lng, lat] = coordinates;
  return validLatLng(lat, lng) ? [lat, lng] : null;
}

function CityMapSelector({ value, onChange }) {
  return <label className="city-map-selector">Map view
    <select aria-label="Map view city" value={value} onChange={(event) => onChange(event.target.value)}>
      {MAP_CITIES.map((city) => <option value={city.id} key={city.id}>{city.name}{city.id === "bengaluru" ? " Â· initial pilot" : ""}</option>)}
    </select>
  </label>;
}

function AdminComplaintCard({ complaint, officials, onOpen }) {
  const coordinates = complaint.location?.coordinates;
  const category = ADMIN_CATEGORIES.find(([value]) => value === complaint.category)?.[1] || complaint.category || "Unclassified";
  const assignedOfficial = officials.find((official) => official.id === complaint.assigned_official_id)?.full_name;
  return <article className="admin-complaint-card">
    <div className="admin-complaint-card__top"><div><div className="admin-complaint-card__badges">{isDemoComplaint(complaint) && <span className="demo-data-badge">Demo data</span>}<span className={`status-tag status-${complaint.status}`}>{complaint.status?.replaceAll("_", " ") || "Status unavailable"}</span></div><h3>{cleanSyntheticText(complaint.title) || category}</h3></div><span className="priority-tag" style={{ "--priority": PRIORITY_COLORS[complaint.priority] }}>{complaint.priority || "Unrated"}</span></div>
    <p className="admin-complaint-card__description">{complaintDescription(complaint)}</p>
    <dl className="admin-complaint-card__meta"><div><dt>Category</dt><dd>{category}</dd></div><div><dt>Location</dt><dd>{coordinates?.length === 2 ? `${coordinates[1].toFixed(4)}, ${coordinates[0].toFixed(4)}` : "Location unavailable"}</dd></div><div><dt>Department</dt><dd>{complaint.department || (complaint.suggested_department_name ? `Suggested: ${complaint.suggested_department_name}` : "Awaiting assignment")}</dd></div><div><dt>Assigned official</dt><dd>{assignedOfficial || (complaint.assigned_official_id ? "Individual assignment recorded" : "Department only")}</dd></div><div><dt>Submitted</dt><dd>{complaint.created_at ? new Date(complaint.created_at).toLocaleDateString() : "Date unavailable"}</dd></div></dl>
    <div className="admin-complaint-card__bottom"><span>{complaint.images?.length ? `${complaint.images.length} evidence file${complaint.images.length === 1 ? "" : "s"}` : "No image evidence"}</span><button type="button" className="button button--outline button--small" onClick={() => onOpen(complaint._id)}>Open record</button></div>
  </article>;
}

function isInternalRoutingEvent(event) {
  return /assign|rout|department/i.test(`${event?.action || ""} ${event?.status || ""}`);
}

function PickLocation({ onPick }) {
  useMapEvents({ click: (event) => onPick(event.latlng) });
  return null;
}

function MapViewportSync({ center, zoom }) {
  const map = useMap();
  useEffect(() => { map.setView(center, zoom, { animate: false }); }, [center, map, zoom]);
  return null;
}

function MapNavigationControls({ center, zoom, cityName, points }) {
  const map = useMap();
  return <div className="nodal-map-controls" aria-label="Map controls">
    <button type="button" aria-label="Zoom in" title="Zoom in" onClick={(event) => { event.stopPropagation(); map.zoomIn(); }}>+</button>
    <button type="button" aria-label="Zoom out" title="Zoom out" onClick={(event) => { event.stopPropagation(); map.zoomOut(); }}>âˆ’</button>
    <button type="button" aria-label="Fit visible report locations" title="Fit visible report locations" disabled={!points.length} onClick={(event) => { event.stopPropagation(); if (points.length === 1) map.setView(points[0], 14); else if (points.length > 1) map.fitBounds(points, { padding: [28, 28], maxZoom: 14 }); }}>â†—</button>
    <button type="button" aria-label={`Return to ${cityName} map view`} title={`Return to ${cityName}`} onClick={(event) => { event.stopPropagation(); map.setView(center, zoom); }}>âŒ–</button>
  </div>;
}

function CityMap({ hotspots = [], complaints = [], onPick, picked, compact = false, center = [12.9716, 77.5946], zoom, cityName = "Bengaluru" }) {
  const mapZoom = zoom ?? (compact ? 10 : 11);
  const validHotspots = hotspots.filter((hotspot) => validLatLng(hotspot.center?.lat, hotspot.center?.lng));
  const validComplaints = complaints.map((complaint) => ({ complaint, point: complaintLatLng(complaint) })).filter((item) => item.point);
  return (
    <div className="city-map-shell">
    <MapContainer center={center} zoom={mapZoom} scrollWheelZoom={!compact} zoomControl={false} keyboard className={`city-map ${compact ? "city-map--compact" : ""}`}>
      <TileLayer attribution="&copy; OpenStreetMap contributors" url="https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png" />
      <MapViewportSync center={center} zoom={mapZoom} />
      {onPick && <PickLocation onPick={onPick} />}
      {validHotspots.map((hotspot) => (
        <Circle key={hotspot.cluster_id} center={[hotspot.center.lat, hotspot.center.lng]} radius={900}
          pathOptions={{ color: "#d97757", fillColor: "#d97757", fillOpacity: .18, weight: 2 }}>
          <Popup><b>Platform hotspot cluster</b><br />{hotspot.count} open reports<br />Common category: {hotspot.top_category}<br />{hotspot.high_priority || 0} marked high priority</Popup>
        </Circle>
      ))}
      {validComplaints.map(({ complaint, point }) => (
        <CircleMarker key={complaint._id}
          center={point}
          radius={compact ? 4 : 6}
          pathOptions={{ color: "#fffdf7", weight: 2, fillColor: PRIORITY_COLORS[complaint.priority] || "#59665d", fillOpacity: .95 }}>
          <Popup><b>{cleanSyntheticText(complaint.category) || "Infrastructure report"}</b><br />{complaintDescription(complaint)}<br />{complaint.status}
            {isDemoComplaint(complaint) && <><br /><span className="demo-data-badge">DEMO DATA</span></>}
          </Popup>
        </CircleMarker>
      ))}
      {picked && validLatLng(picked.lat, picked.lng) && <CircleMarker center={[picked.lat, picked.lng]} radius={8} pathOptions={{ color: "#263f35", fillColor: "#d97757", fillOpacity: .9, weight: 2 }} />}
      <MapNavigationControls center={center} zoom={mapZoom} cityName={cityName} points={validComplaints.map((item) => item.point)} />
    </MapContainer>
    <MapLegend hotspots={validHotspots.length > 0} complaints={validComplaints.length > 0} picked={Boolean(picked)} />
    </div>
  );
}

function MapLegend({ hotspots, complaints, picked }) {
  return <ul className="map-legend" aria-label="Map legend">
    {hotspots && <li><i className="map-legend__hotspot" />Hotspot cluster</li>}
    {complaints && <><li><i style={{ backgroundColor: PRIORITY_COLORS.high }} />High priority</li><li><i style={{ backgroundColor: PRIORITY_COLORS.medium }} />Medium priority</li><li><i style={{ backgroundColor: PRIORITY_COLORS.low }} />Low priority</li></>}
    {picked && <li><i className="map-legend__selected" />Selected report location</li>}
    {!hotspots && !complaints && !picked && <li>Map location view</li>}
  </ul>;
}

function CitizenComplaintCards({ complaints, loading, error, onOpen }) {
  if (loading && !complaints.length) return <div className="empty-state" role="status"><Clock3 size={22} /><h3>Loading your reports</h3><p>Your complaint history will appear here.</p></div>;
  if (error && !complaints.length) return <div className="empty-state" role="alert"><CircleAlert size={22} /><h3>Reports could not be loaded</h3><p>{error}</p></div>;
  if (!complaints.length) return <div className="empty-state"><Leaf size={23} /><h3>No reports match these filters.</h3><p>Clear one or more filters, or submit a report to begin tracking it here.</p></div>;
  return <>{error && <p role="alert" className="form-error citizen-list-error">Reports could not be refreshed. {error}</p>}<div className="citizen-report-list">{complaints.map((row) => {
    const demo = isDemoComplaint(row);
    const location = row.location?.coordinates?.length === 2
      ? `${row.location.coordinates[1].toFixed(4)}, ${row.location.coordinates[0].toFixed(4)}` : "Location unavailable";
    return <article className="citizen-report-card" key={row._id}>
      <div className="citizen-report-card__top">
        <div className="citizen-report-card__tags"><span className={`status-tag status-${row.status || "submitted"}`}>{(row.status || "submitted").replaceAll("_", " ")}</span>{demo && <span className="demo-data-badge">DEMO DATA</span>}</div>
        <span className="priority-tag" style={{ "--priority": PRIORITY_COLORS[row.priority] || "#5d785f" }}>{row.priority || "Priority unset"}</span>
      </div>
      <h3>{cleanSyntheticText(row.category?.replaceAll("_", " ")) || "Infrastructure report"}</h3>
      <p className="citizen-report-card__description">{complaintDescription(row)}</p>
      <div className="citizen-report-card__meta"><span><MapPin size={14} />{location}</span><span><Building2 size={14} />{row.department || (row.awaiting_department_review ? "Awaiting department review" : "Awaiting assignment")}</span><span><Clock3 size={14} />{row.created_at ? new Date(row.created_at).toLocaleDateString() : "Date unavailable"}</span></div>
      <div className="citizen-report-card__bottom"><span>{row.images?.length ? `${row.images.length} image${row.images.length === 1 ? "" : "s"} attached` : "No images attached"}</span><button type="button" className="button button--outline button--small" aria-label={`View details for ${cleanSyntheticText(row.category) || "complaint"}`} onClick={() => onOpen(row._id)}>View details <ArrowRight size={15} /></button></div>
    </article>;
  })}</div></>;
}

function OfficialWorkSummary({ complaints, loading, error }) {
  const assigned = complaints.filter((row) => row.assigned_to_viewer).length;
  const pending = complaints.filter((row) => row.status === "assigned").length;
  const inProgress = complaints.filter((row) => row.status === "in_progress").length;
  const review = complaints.filter((row) => row.status === "resolution_submitted").length;
  const statusLabels = { submitted: "Submitted", open: "Open", triaged: "Triaged", assigned: "Assigned", in_progress: "In progress", resolution_submitted: "Awaiting review", resolved: "Resolved", disputed: "Disputed", reopening_requested: "Reopening requested", unknown: "Status unavailable" };
  const distribution = [...new Set(complaints.map((row) => row.status || "unknown"))]
    .map((status) => ({ status, label: statusLabels[status] || status.replaceAll("_", " "), count: complaints.filter((row) => (row.status || "unknown") === status).length }));
  const total = complaints.length;
  return <section className="official-summary" aria-label="Authorized workload summary">
    <div className="dashboard-stats dashboard-stats--official">
      <Stat value={loading && !total ? null : assigned} label="Assigned to me" icon={UserRound} />
      <Stat value={loading && !total ? null : pending} label="Pending action" icon={Clock3} />
      <Stat value={loading && !total ? null : inProgress} label="In progress" icon={Construction} />
      <Stat value={loading && !total ? null : review} label="Awaiting admin review" icon={Check} />
    </div>
    <div className="official-status-panel">
      <div className="official-status-panel__heading"><div><span className="eyebrow">Work status</span><h2>Status distribution</h2></div><span>{total} authorized report{total === 1 ? "" : "s"}</span></div>
      {loading && !total ? <p className="empty-note">Loading your permitted worklist...</p>
        : error && !total ? <p role="alert" className="form-error">Workload could not be loaded: {error}</p>
          : distribution.length ? <>
            <div className="official-status-bar" role="img" aria-label={distribution.map((item) => `${item.label}: ${item.count}`).join(", ")}>
              {distribution.map((item) => <span key={item.status} className={`official-status-bar__segment status-${item.status}`} style={{ width: `${(item.count / total) * 100}%` }} />)}
            </div>
            <ul className="official-status-legend">{distribution.map((item) => <li key={item.status}><span className={`official-status-dot status-${item.status}`} /><span>{item.label}</span><strong>{item.count}</strong></li>)}</ul>
          </> : <div className="official-summary-empty"><Leaf size={19} /><span>No authorized complaints are currently assigned to your department or account.</span></div>}
    </div>
  </section>;
}

function OfficialWorkCard({ complaint, department, onOpen }) {
  const coordinates = complaint.location?.coordinates;
  const location = coordinates?.length === 2
    ? `${coordinates[1].toFixed(5)}, ${coordinates[0].toFixed(5)}` : "Location unavailable";
  const title = cleanSyntheticText(complaint.title) || cleanSyntheticText(complaint.category?.replaceAll("_", " ")) || "Infrastructure report";
  return <article className="official-work-card">
    <div className="official-work-card-top"><span className={`status-tag status-${complaint.status || "submitted"}`}>{(complaint.status || "submitted").replaceAll("_", " ")}</span><span className="priority-tag" style={{ "--priority": PRIORITY_COLORS[complaint.priority] || "#5d785f" }}>{complaint.priority || "Priority unset"}</span></div>
    <div className="official-work-card__title-row"><h3>{title}</h3>{isDemoComplaint(complaint) && <span className="demo-data-badge">DEMO DATA</span>}</div>
    <p className="official-work-description">{complaintDescription(complaint)}</p>
    <dl className="official-work-card__meta">
      <div><dt>Category</dt><dd>{cleanSyntheticText(complaint.category?.replaceAll("_", " ")) || "Not set"}</dd></div>
      <div><dt>Location</dt><dd><MapPin size={13} />{location}</dd></div>
      <div><dt>Department</dt><dd>{complaint.department || department || "Unassigned"}</dd></div>
      <div><dt>Assignment</dt><dd>{complaint.assigned_to_viewer ? "Assigned to you" : "Department work queue"}</dd></div>
      <div><dt>Submitted</dt><dd>{complaint.created_at ? new Date(complaint.created_at).toLocaleDateString() : "Date unavailable"}</dd></div>
      <div><dt>Evidence</dt><dd>{complaint.images?.length ? `${complaint.images.length} attached image${complaint.images.length === 1 ? "" : "s"}` : "No attached images"}</dd></div>
    </dl>
    <button type="button" className="button button--forest button--small" onClick={() => onOpen(complaint._id)}>Open complaint <ArrowRight size={15} /></button>
  </article>;
}

function SiteMark({ inverse = false, homeHref = "#top", onHome }) {
  function handleHome(event) {
    if (!onHome) return;
    event.preventDefault();
    onHome();
  }
  return <a href={homeHref} onClick={handleHome} className={`site-mark ${inverse ? "site-mark--inverse" : ""}`} aria-label="NODAL home"><span className="mark-symbol" aria-hidden="true">N</span><span>NODAL<small>PUBLIC INFRASTRUCTURE INTELLIGENCE</small></span></a>;
}

function Stat({ value, label, icon: Icon }) {
  return <div className="stat"><span className="stat-icon"><Icon size={17} strokeWidth={1.7} /></span><strong>{value ?? "ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â"}</strong><span>{label}</span></div>;
}

function AdminOverviewPanel({ overview, loading, onRefresh }) {
  const counts = overview?.status_counts || {};
  return <section className="admin-overview" aria-label="Administrator overview">
    <div className="admin-status-metrics">
      <Stat value={overview?.total_complaints} label="Total complaints" icon={MapPinned} />
      <Stat value={counts.submitted} label="Submitted" icon={Sparkles} />
      <Stat value={counts.assigned} label="Assigned" icon={UserRound} />
      <Stat value={counts.in_progress} label="In progress" icon={Construction} />
      <Stat value={counts.resolution_submitted} label="Awaiting resolution review" icon={Clock3} />
      <Stat value={counts.resolved} label="Resolved" icon={Check} />
    </div>
    <div className="admin-overview-grid">
      <section className="admin-workload-panel" aria-labelledby="department-workload-title">
        <div className="section-row"><div><span className="eyebrow">Current assignments</span><h2 id="department-workload-title">Department workload</h2></div><button className="button button--outline button--small" onClick={onRefresh} disabled={loading}>{loading ? "RefreshingÃ¢â‚¬Â¦" : "Refresh overview"}</button></div>
        {loading && !overview ? <p className="empty-note">Loading administrator overview...</p> : overview?.department_workload?.length ? <div className="admin-workload-list">{overview.department_workload.map((department) => <article className="admin-workload-row" key={department.department_id || department.department}><div><strong>{department.department}</strong><small>{department.active === false ? "Inactive registry department" : department.active === null ? "Legacy or unregistered department" : "Active registry department"}</small><span>{department.assigned || 0} assigned | {department.in_progress || 0} in progress | {department.resolution_submitted || 0} awaiting review</span><span className="admin-workload-track" aria-label={`${department.total || 0} complaints`}><i style={{ width: `${Math.min(100, ((department.total || 0) / Math.max(1, ...overview.department_workload.map((row) => row.total || 0))) * 100)}%` }} /></span></div><b>{department.total || 0}</b></article>)}</div> : <p className="empty-note">No department workload yet.</p>}
      </section>
      <aside className="admin-queue-panel" aria-label="Administrator queues">
        <a href="#admin-review"><span><ShieldCheck size={17} />Pending official access</span><strong>{overview?.pending_official_requests ?? "ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â"}</strong></a>
        <a href="#resolution-review"><span><Clock3 size={17} />Resolutions to review</span><strong>{overview?.resolutions_awaiting_review ?? "ÃƒÂ¢Ã¢â€šÂ¬Ã¢â‚¬Â"}</strong></a>
        <p>{overview?.data_notice || "Counts may include unverified demonstration records."}</p>
      </aside>
    </div>
  </section>;
}

function Landing({ overview, hotspots, onAuth }) {
  const [selectedCityId, setSelectedCityId] = useState("bengaluru");
  const selectedCity = MAP_CITIES.find((city) => city.id === selectedCityId) || MAP_CITIES[0];
  const categories = [
    [Construction, "Roads and footpaths"],
    [Trash2, "Waste and cleanliness"],
    [Droplets, "Water and drainage"],
    [Lightbulb, "Street lighting"],
  ];
  return (
    <main id="top" className="landing">
      <section className="hero-section">
        <img className="hero-photo" src={heroImage} alt="Illustrative, AI-generated tree-lined neighborhood street; not a documentary photograph" />
        <div className="hero-shade" />
        <nav className="top-nav top-nav--hero" aria-label="Main navigation">
          <SiteMark inverse />
          <div className="nav-links"><a href="#platform">The platform</a><a href="#intelligence">City intelligence</a><a href="#how-it-works">How it works</a></div>
          <div className="nav-actions"><button className="text-button text-button--light" onClick={() => onAuth("login")}>Sign in <ArrowUpRight size={15} /></button><button className="button button--light" onClick={() => onAuth("register")}>Join NODAL</button></div>
        </nav>
        <div className="hero-copy">
          <p className="eyebrow eyebrow--light"><span /> Public infrastructure, understood together</p>
          <h1>See the systems<br /><em>that shape everyday life.</em></h1>
          <p className="hero-intro">NODAL connects local infrastructure reports into a clearer shared picture for people and civic teams across Indian cities.</p>
          <div className="hero-actions"><button className="button button--terracotta" onClick={() => onAuth("register")}>Share a local concern <ArrowUpRight size={17} /></button><a className="hero-secondary" href="#intelligence">Explore the platform <ArrowDown size={16} /></a></div>
        </div>
        <div className="hero-caption"><span>India-wide platform</span><span>Bengaluru is the initial pilot</span></div>
      </section>

      <section id="platform" className="intro-band page-gutter">
        <div className="intro-kicker"><span className="kicker-line" />Built for India's cities</div>
        <p>Infrastructure is experienced one street at a time. NODAL helps bring local perspectives into focus, beginning with a Bengaluru pilot.</p>
      </section>

      <section className="stats-band page-gutter" aria-label="Platform-wide overview">
        <div className="stats-heading"><span className="eyebrow">Platform-wide snapshot</span><p>What current NODAL records show</p></div>
        <Stat value={overview?.total} label="Reports across the platform" icon={MapPinned} />
        <Stat value={overview?.open} label="Open across the platform" icon={Clock3} />
        <Stat value={overview?.high_priority} label="Marked high priority" icon={CircleAlert} />
        <Stat value={overview?.hotspot_count} label="Grouped areas returned" icon={Activity} />
        <p className="data-notice"><CircleAlert size={15} /> {overview?.data_notice || "Platform counts are unavailable right now. Figures may include unverified demonstration records; they are not civic statistics."}</p>
      </section>

      <section id="how-it-works" className="how-section page-gutter">
        <div className="section-heading"><div><span className="eyebrow">A practical way forward</span><h2>Local knowledge.<br /><em>Connected insight.</em></h2></div><p>Residents see the details of a place. Shared reporting can help make recurring infrastructure concerns easier to understand.</p></div>
        <div className="steps-grid">
          {[['01', 'Notice', 'Start with what you observe in a place.'], ['02', 'Report', 'Describe the concern and mark its location.'], ['03', 'Follow', 'Keep a clear record of your report and its updates.']].map(([number, title, copy]) => <article className="step-card" key={number}><span>{number}</span><h3>{title}</h3><p>{copy}</p><ArrowUpRight size={18} /></article>)}
        </div>
      </section>

      <section className="category-section page-gutter">
        <div className="section-heading section-heading--compact"><div><span className="eyebrow">Infrastructure in daily life</span><h2>Connected by place,<br /><em>not by category.</em></h2></div><p>Reports can describe the systems people encounter every day.</p></div>
        <div className="infrastructure-ribbon">{categories.map(([Icon, title]) => <div className="infrastructure-signal" key={title}><span><Icon size={19} strokeWidth={1.7} /></span><strong>{title}</strong><ChevronRight size={15} /></div>)}</div>
      </section>

      <section id="intelligence" className="city-section intelligence-section">
        <div className="city-copy"><span className="eyebrow eyebrow--light"><Globe2 size={15} /> Platform-wide intelligence</span><h2>Many places.<br /><em>A shared view.</em></h2><p>NODAL is being shaped for cities across India. Bengaluru is the initial pilot. This map shows only the hotspot clusters returned by the current platform API; it is not a government feed or a live operational map.</p><div className="pilot-note"><span><Building2 size={17} /></span><div><small>Initial pilot</small><strong>Bengaluru, Karnataka</strong></div></div><button className="text-button text-button--light" onClick={() => onAuth("register")}>Add a local perspective <ArrowUpRight size={15} /></button></div>
        <div className="city-map-frame intelligence-map-frame"><div className="intelligence-map-heading"><div className="map-label"><MapPinned size={15} /> PLATFORM HOTSPOT CLUSTERS</div><CityMapSelector value={selectedCityId} onChange={setSelectedCityId} /></div><CityMap hotspots={hotspots} compact center={selectedCity.center} zoom={selectedCity.zoom} cityName={selectedCity.name} /><div className="map-footnote">Map view: {selectedCity.name}. Selection moves the map only; the API returns platform-wide hotspot clusters, not city-filtered intelligence. {overview?.data_notice || "Records may include unverified demonstration data."}</div></div>
      </section>

      <section className="audience-section page-gutter">
        <div className="audience-card audience-card--citizen"><span className="audience-icon"><UserRound size={20} /></span><span className="eyebrow">For residents</span><h3>Bring your local<br />view into focus.</h3><p>Report an infrastructure concern and follow the updates connected to your account.</p><button className="button button--forest" onClick={() => onAuth("register")}>Create a resident account <ArrowRight size={16} /></button></div>
        <div className="audience-card audience-card--official"><span className="audience-icon"><ShieldCheck size={20} /></span><span className="eyebrow">For civic teams</span><h3>Work from a clearer<br />picture of place.</h3><p>Official access remains subject to independent administrator verification.</p><button className="button button--outline" onClick={() => onAuth("login")}>Official sign in <ArrowRight size={16} /></button></div>
      </section>

      <section className="final-cta page-gutter"><div><span className="eyebrow">Attention begins close to home</span><h2>Start with what<br /><em>you notice.</em></h2></div><button className="button button--terracotta" onClick={() => onAuth("register")}>Share a concern <ArrowUpRight size={17} /></button></section>
      <footer className="site-footer page-gutter"><SiteMark /><div><span>Connecting the systems that matter.</span><span className="footer-note">India-wide platform / Bengaluru initial pilot</span></div><a className="footer-contact" href="mailto:nodalcontactdesk@gmail.com">nodalcontactdesk@gmail.com</a><a href="#top">Back to top <ArrowUpRight size={13} /></a></footer>
    </main>
  );
}

function AuthPanel({ mode, setMode, onSuccess, onBack }) {
  const [form, setForm] = useState({ full_name: "", email: "", password: "" });
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const registering = mode === "register";

  async function submit(event) {
    event.preventDefault();
    setBusy(true);
    setError("");
    try {
      const data = await request(registering ? "/auth/register" : "/auth/login", { method: "POST", body: form });
      // The API establishes the cookie session. The returned role selects the
      // existing role-specific workspace in App without a client-side role choice.
      onSuccess(data.user);
    } catch (err) {
      setError(err.message);
    } finally {
      setBusy(false);
    }
  }

  function switchMode() {
    setMode(registering ? "login" : "register");
    setError("");
  }

  return (
    <main id="top" className="auth-page auth-page--editorial">
      <aside className="auth-photo auth-photo--editorial" style={{ backgroundImage: `url(${heroImage})` }} aria-label="NODAL introduction">
        <button type="button" className="back-link" onClick={onBack}><ArrowDown size={14} /> Back to NODAL</button>
        <div className="auth-photo-copy"><span className="eyebrow eyebrow--light">A shared view of public infrastructure</span><p>"Every street has a story.<br /><em>Every perspective matters.</em>"</p><div className="auth-pilot-note"><Globe2 size={15} /> India-wide platform, beginning with Bengaluru</div></div>
      </aside>
      <section className="auth-content auth-content--editorial" aria-labelledby="auth-title">
        <SiteMark onHome={onBack} />
        <span className="eyebrow">{registering ? "Create your resident account" : "Resident, official or administrator"}</span>
        <h1 id="auth-title">{registering ? "Make your local view count." : "Welcome back."}</h1>
        <p className="auth-subtitle">{registering ? "Join NODAL to report an infrastructure concern and follow its progress." : "Sign in to continue to the workspace connected to your account."}</p>
        <form onSubmit={submit} className="auth-form auth-form--editorial" aria-busy={busy}>
          {registering && <label htmlFor="auth-full-name">Full name<input id="auth-full-name" name="full_name" autoComplete="name" required maxLength={120} value={form.full_name} onChange={(event) => setForm({ ...form, full_name: event.target.value })} aria-invalid={Boolean(error)} /></label>}
          <label htmlFor="auth-email">Email address<input id="auth-email" name="email" type="email" autoComplete="email" required maxLength={254} value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} aria-invalid={Boolean(error)} /></label>
          <label htmlFor="auth-password">Password<input id="auth-password" name="password" type="password" autoComplete={registering ? "new-password" : "current-password"} minLength={registering ? 12 : undefined} maxLength={256} required value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} aria-describedby={registering ? "auth-password-hint" : undefined} aria-invalid={Boolean(error)} />{registering && <small id="auth-password-hint">Use at least 12 characters.</small>}</label>
          {error && <p id="auth-error" role="alert" className="form-error"><CircleAlert size={16} aria-hidden="true" />{error}</p>}
          {busy && <p className="auth-progress" role="status" aria-live="polite">{registering ? "Creating your resident account..." : "Signing in securely..."}</p>}
          <button className="button button--forest button--wide auth-submit" disabled={busy} aria-busy={busy}><span>{busy ? "Please wait..." : registering ? "Create resident account" : "Sign in"}</span><ArrowRight size={16} aria-hidden="true" /></button>
        </form>
        <p className="auth-switch">{registering ? "Already have an account?" : "New to NODAL?"} <button type="button" onClick={switchMode}>{registering ? "Sign in" : "Create a resident account"}</button></p>
        <p className="auth-role-note"><ShieldCheck size={15} aria-hidden="true" /> Public registration creates resident accounts only. Official access requires independent administrator verification.</p>
      </section>
    </main>
  );
}

function OfficialAccessRequest() {
  const [form, setForm] = useState({ employee_id: "", department: "", designation: "", verification_information: "" });
  const [status, setStatus] = useState("");
  const [error, setError] = useState("");
  async function submit(event) {
    event.preventDefault(); setError(""); setStatus("");
    try { await request("/auth/official-access-requests", { method: "POST", body: form }); setStatus("Your request is pending independent administrator review."); setForm({ employee_id: "", department: "", designation: "", verification_information: "" }); }
    catch (err) { setError(err.message); }
  }
  return <section className="workflow-card"><div className="workflow-title"><ShieldCheck size={19} /><div><h3>Request official access</h3><p>Requests remain pending until an administrator independently verifies them.</p></div></div>
    <form className="compact-form" onSubmit={submit}><div className="form-two"><label>Employee ID<input required maxLength={120} value={form.employee_id} onChange={(e) => setForm({ ...form, employee_id: e.target.value })} /></label><label>Department<input required maxLength={160} value={form.department} onChange={(e) => setForm({ ...form, department: e.target.value })} /></label><label>Designation<input required maxLength={160} value={form.designation} onChange={(e) => setForm({ ...form, designation: e.target.value })} /></label></div><label>Supporting verification information<textarea required maxLength={2000} rows={3} placeholder="Provide contact details or context that helps an administrator verify your request independently." value={form.verification_information} onChange={(e) => setForm({ ...form, verification_information: e.target.value })} /></label><p className="form-caution"><CircleAlert size={14} /> An email domain or uploaded ID alone does not establish government employment.</p>{error && <p className="form-error">{error}</p>}{status && <p className="form-success"><Check size={15} />{status}</p>}<button className="button button--forest">Send for review <ArrowRight size={15} /></button></form>
  </section>;
}

function AdminVerificationQueue() {
  const [requests, setRequests] = useState([]);
  const [departments, setDepartments] = useState([]);
  const [requestStatus, setRequestStatus] = useState("pending");
  const [forms, setForms] = useState({});
  const [notice, setNotice] = useState("");
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => { setLoading(true); setError(""); try { setRequests(await request(`/admin/official-access-requests?status=${requestStatus}`)); } catch (err) { setError(err.message); } finally { setLoading(false); } }, [requestStatus]);
  useEffect(() => {
    let alive = true;
    request(`/admin/official-access-requests?status=${requestStatus}`).then((rows) => { if (alive) setRequests(rows); }).catch((err) => { if (alive) setError(err.message); }).finally(() => { if (alive) setLoading(false); });
    request("/admin/departments").then((rows) => { if (alive) setDepartments(rows.filter((row) => row.active)); }).catch((err) => { if (alive) setError(err.message); });
    return () => { alive = false; };
  }, [requestStatus]);
  function update(id, patch) { setForms((prev) => { const row = requests.find((item) => item.id === id); const mapped = departments.find((item) => item.name.toLowerCase() === row?.department?.toLowerCase()); return { ...prev, [id]: { verification_method: "", verification_notes: "", decision_notes: "", department_id: mapped?.id || "", independently_verified: false, ...prev[id], ...patch } }; }); }
  async function decide(row, decision) {
    const data = forms[row.id] || {};
    setError(""); setNotice("");
    if (decision === "reject" && !data.decision_notes?.trim()) { setError("Add a reason before rejecting this request."); return; }
    try { await request(`/admin/official-access-requests/${row.id}/decision`, { method: "POST", body: { decision, ...data, notes: decision === "reject" ? data.decision_notes.trim() : undefined } }); setNotice(`Request ${decision === "approve" ? "approved" : "rejected"}.`); await load(); }
    catch (err) { setError(err.message); }
  }
  return <section className="workflow-card"><div className="workflow-title"><ShieldCheck size={19} /><div><h3>Official access requests</h3><p>Review and document independent verification before granting a role.</p></div><button className="button button--outline button--small" onClick={load} disabled={loading}>Refresh</button></div>
    <div className="admin-request-filter"><label>Request status<select value={requestStatus} onChange={(event) => { setLoading(true); setError(""); setRequests([]); setRequestStatus(event.target.value); }}><option value="pending">Pending</option><option value="approved">Approved</option><option value="rejected">Rejected</option><option value="all">All requests</option></select></label></div>
    {error && <p className="form-error">{error}</p>}{notice && <p className="form-success"><Check size={15} />{notice}</p>}
    {loading ? <p className="empty-note" role="status">Loading {requestStatus} requests...</p> : !requests.length && !error && <p className="empty-note">No {requestStatus} requests.</p>}
    <div className="request-list">{requests.map((row) => { const values = forms[row.id] || { department_id: departments.find((item) => item.name.toLowerCase() === row.department?.toLowerCase())?.id || "" }; const synthetic = /\.test$/i.test(row.email || ""); return <article className="request-card admin-verification-card" key={row.id}><div className="request-person">{synthetic && <span className="demo-data-badge">Synthetic test applicant</span>}<span className="status-tag">{row.status === "approved" ? "Approved" : row.status === "rejected" ? "Rejected" : "Pending verification"}</span><strong>{row.full_name}</strong><span>{row.email}</span><span>{row.designation} Ã‚Â· {row.department}</span><span>Employee ID: {row.employee_id}</span><p>{row.verification_information}</p></div><div className="verification-fields">{row.status === "pending" ? <><label>Independent verification method<select value={values.verification_method || ""} onChange={(e) => update(row.id, { verification_method: e.target.value })}><option value="">Choose a method</option><option value="department_contact">Direct department contact using independently sourced details</option><option value="official_directory">Confirmed through an official public directory</option><option value="supervisor_confirmation">Confirmed with a known supervisor/contact</option></select></label><label>Verification notes<textarea rows={2} value={values.verification_notes || ""} onChange={(e) => update(row.id, { verification_notes: e.target.value })} /></label><label>Approved registry department<select required value={values.department_id || ""} onChange={(e) => update(row.id, { department_id: e.target.value })}><option value="">Choose an active department</option>{departments.map((department) => <option key={department.id} value={department.id}>{department.name}</option>)}</select></label><label className="check-row"><input type="checkbox" checked={values.independently_verified || false} onChange={(e) => update(row.id, { independently_verified: e.target.checked })} /> I independently verified this person's employment</label><label>Reason for rejection<textarea rows={2} maxLength={2000} value={values.decision_notes || ""} onChange={(e) => update(row.id, { decision_notes: e.target.value })} placeholder="Required when rejecting this request" /></label><div className="button-row"><button className="button button--forest button--small" disabled={synthetic || row.status !== "pending"} onClick={() => decide(row, "approve")}>Approve official access</button>{synthetic && <p className="form-caution">Synthetic test applicants cannot be approved as real officials.</p>}<button className="button button--reject button--small" disabled={row.status !== "pending"} onClick={() => decide(row, "reject")}>Reject</button></div></> : <p className="empty-note">This request has been {row.status}.</p>}</div></article>; })}</div>
  </section>;
}

const DEPARTMENT_CATEGORIES = [
  ["pothole", "Road damage"], ["garbage", "Waste and cleanliness"],
  ["waterlogging", "Waterlogging"], ["drainage", "Drainage"],
  ["streetlight", "Street lighting"], ["water_leak", "Water leakage"],
  ["damaged_infrastructure", "Damaged infrastructure"],
  ["other", "Other"], ["unclassified", "Unclassified"],
];

function AdminDepartmentManager() {
  const [departments, setDepartments] = useState([]);
  const [unmapped, setUnmapped] = useState([]);
  const [loading, setLoading] = useState(true);
  const [editingId, setEditingId] = useState("");
  const [form, setForm] = useState({ department_id: "", name: "", description: "", active: true, categories: [] });
  const [error, setError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const [rows, reviewRows] = await Promise.all([request("/admin/departments"), request("/admin/complaints/unmapped")]);
      setDepartments(rows); setUnmapped(reviewRows);
    } catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }, []);
  useEffect(() => {
    let alive = true;
    Promise.all([request("/admin/departments"), request("/admin/complaints/unmapped")])
      .then(([rows, reviewRows]) => { if (alive) { setDepartments(rows); setUnmapped(reviewRows); } })
      .catch((err) => { if (alive) setError(err.message); })
      .finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, []);
  function reset() { setEditingId(""); setForm({ department_id: "", name: "", description: "", active: true, categories: [] }); }
  function edit(row) {
    setEditingId(row.id);
    setForm({ department_id: row.id, name: row.name, description: row.description, active: row.active, categories: row.categories || [] });
    setError(""); setNotice("");
  }
  function toggleCategory(category) {
    setForm((old) => ({ ...old, categories: old.categories.includes(category)
      ? old.categories.filter((item) => item !== category) : [...old.categories, category] }));
  }
  async function save(event) {
    event.preventDefault(); setBusy(true); setError(""); setNotice("");
    try {
      const path = editingId ? `/admin/departments/${editingId}` : "/admin/departments";
      await request(path, { method: editingId ? "PATCH" : "POST", body: form });
      setNotice(editingId ? "Department updated." : "Department created."); reset(); await load();
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  async function toggleActive(row) {
    setError(""); setNotice("");
    try { await request(`/admin/departments/${row.id}`, { method: "PATCH", body: { active: !row.active } }); setNotice(`Department ${row.active ? "deactivated" : "activated"}.`); await load(); }
    catch (err) { setError(err.message); }
  }
  return <section className="complaints-section department-manager">
    <div className="section-row"><div><span className="eyebrow">Configurable routing</span><h2>Department registry</h2><p className="routing-caution">Prototype routing groups and mappings are suggestions only; they are not verified government assignments.</p></div><button className="button button--outline button--small" onClick={load}>Refresh registry</button></div>
    {error && <p role="alert" className="form-error">{error}</p>}{notice && <p role="status" className="form-success">{notice}</p>}
    <div className="department-layout"><div className="department-list">{departments.map((row) => <article className="department-card" key={row.id}><div><span className={`status-tag ${row.active ? "status-active" : ""}`}>{row.active ? "Active" : "Inactive"}</span><h3>{row.name}</h3><small>{row.id}</small><p>{row.description}</p><p><strong>Categories:</strong> {row.categories.length ? row.categories.map((key) => DEPARTMENT_CATEGORIES.find(([value]) => value === key)?.[1] || key).join(", ") : "None"}</p></div><div className="button-row"><button className="button button--outline button--small" onClick={() => edit(row)}>Edit</button><button className="button button--outline button--small" onClick={() => toggleActive(row)}>{row.active ? "Deactivate" : "Activate"}</button></div></article>)}{loading ? <p className="empty-note">Loading departmentsÃ¢â‚¬Â¦</p> : !departments.length && <p className="empty-note">No departments are configured.</p>}</div>
      <form className="compact-form department-form" onSubmit={save}><h3>{editingId ? "Edit department" : "Add department"}</h3><label>Department ID<input required pattern="[a-z0-9]+(-[a-z0-9]+)*" disabled={Boolean(editingId)} value={form.department_id} onChange={(e) => setForm({ ...form, department_id: e.target.value })} placeholder="road-infrastructure" /></label><label>Name<input required maxLength={160} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} /></label><label>Description<textarea maxLength={2000} rows={3} value={form.description} onChange={(e) => setForm({ ...form, description: e.target.value })} /></label><fieldset className="category-mappings"><legend>Category mappings</legend>{DEPARTMENT_CATEGORIES.map(([key, label]) => <label className="check-row" key={key}><input type="checkbox" checked={form.categories.includes(key)} onChange={() => toggleCategory(key)} />{label}</label>)}</fieldset>{error && <p className="form-error">{error}</p>}<div className="button-row"><button className="button button--forest button--small" disabled={busy}>{busy ? "SavingÃ¢â‚¬Â¦" : editingId ? "Save department" : "Create department"}</button>{editingId && <button type="button" className="button button--outline button--small" onClick={reset}>Cancel</button>}</div></form></div>
    <div className="unmapped-review"><div className="section-row"><div><span className="eyebrow">Needs a routing rule</span><h3>Unmapped complaints</h3></div><strong>{loading ? "Ã¢â‚¬Â¦" : unmapped.length}</strong></div>{loading ? <p className="empty-note">Loading unmapped complaintsÃ¢â‚¬Â¦</p> : unmapped.length ? <div className="request-list">{unmapped.map((row) => <article className="request-card" key={row._id}><div className="request-person">{isDemoComplaint(row) && <span className="demo-data-badge">Demo data</span>}<strong>{complaintDescription(row)}</strong><span>Category: {row.category || "missing"}</span><span>{row.status?.replaceAll("_", " ")}</span></div><p>Assign a department after reviewing this report. Suggested: {row.suggested_department_name || "No active category mapping"}</p></article>)}</div> : <p className="empty-note">All current resident-report categories have active mappings.</p>}</div>
  </section>;
}

function ProfilePanel({ user, onUpdated }) {
  const [fullName, setFullName] = useState(user.full_name || "");
  const [busy, setBusy] = useState(false);
  const [message, setMessage] = useState("");
  const [error, setError] = useState("");
  async function save(event) {
    event.preventDefault(); setBusy(true); setError(""); setMessage("");
    try {
      const result = await request("/auth/profile", { method: "PATCH", body: { full_name: fullName } });
      setFullName(result.user.full_name); onUpdated(result.user); setMessage("Profile updated.");
    } catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  return <section id="profile" className="complaints-section profile-panel"><div className="section-row"><div><span className="eyebrow">Your account</span><h2>Profile</h2></div></div><div className="profile-layout"><form className="compact-form" onSubmit={save}><label>Full name<input required maxLength={120} value={fullName} onChange={(event) => setFullName(event.target.value)} /></label><label>Email address<input value={user.email} readOnly /></label><div className="profile-role"><span>Access role</span><strong>{user.role}{user.department ? ` Ã‚Â· ${user.department}` : ""}</strong><small>{user.role === "official" ? "Administrator-verified account" : user.role === "citizen" ? "Resident access" : "Administrator access"}</small></div>{error && <p className="form-error">{error}</p>}{message && <p className="form-success">{message}</p>}<button className="button button--forest button--small" disabled={busy}>{busy ? "SavingÃ¢â‚¬Â¦" : "Save profile"}</button></form></div></section>;
}

function ComplaintDetailPanel({ complaint, loading, error, onClose, isCitizen, isOfficial, isAdmin, officials = [], onOfficialAction, onAdminReview, actionBusy, disputeNote, onDisputeNoteChange, onDispute, submittingDispute }) {
  const [officialNotes, setOfficialNotes] = useState("");
  const [officialEvidence, setOfficialEvidence] = useState("");
  const [officialError, setOfficialError] = useState("");
  const [adminReviewNotes, setAdminReviewNotes] = useState("");
  const [adminReviewEvidence, setAdminReviewEvidence] = useState(() => {
    const submission = [...(complaint?.status_history || [])].reverse().find((event) => event.status === "resolution_submitted");
    return (submission?.evidence || []).join("\n");
  });
  const [adminReviewError, setAdminReviewError] = useState("");
  if (!loading && !error && !complaint) return null;
  const apiBase = import.meta.env.VITE_API_BASE || "http://localhost:5000";
  function safeEvidenceUrl(reference) {
    try {
      const url = new URL(reference);
      return ["https:", "http:"].includes(url.protocol) ? url.href : null;
    } catch { return null; }
  }
  return <section className="complaint-detail" aria-labelledby="complaint-detail-title" aria-live="polite">
    <div className="section-row"><div><span className="eyebrow">{isOfficial ? "Authorized work item" : "Your report record"}</span><h3 id="complaint-detail-title">Complaint details</h3></div>{onClose && <button type="button" className="button button--outline button--small" onClick={onClose}>Close details</button>}</div>
    {loading && <p className="empty-note">Loading complaint detailsÃ¢â‚¬Â¦</p>}
    {error && <p role="alert" className="form-error">{error}</p>}
    {complaint && <>
      <div className="complaint-detail-summary"><div className="complaint-detail-heading"><h4>{isOfficial ? cleanSyntheticText(complaint.category?.replaceAll("_", " ")) || "Infrastructure report" : complaintDescription(complaint)}</h4>{isDemoComplaint(complaint) && <span className="demo-data-badge">DEMO DATA</span>}</div>{isOfficial && <p className="official-complaint-description">{complaintDescription(complaint)}</p>}<dl>
        <div><dt>Category</dt><dd>{cleanSyntheticText(complaint.category) || "Not set"}</dd></div>
        <div><dt>Priority</dt><dd>{complaint.priority || "Not set"}</dd></div>
        <div><dt>Current status</dt><dd>{(complaint.status || "submitted").replaceAll("_", " ")}</dd></div>
        <div><dt>Suggested department</dt><dd>{complaint.suggested_department_name || "No active mapping"}</dd></div>
        <div><dt>Assigned department</dt><dd>{complaint.department || "Not assigned"}</dd></div>
        {isAdmin && <div><dt>Assigned official</dt><dd>{officials.find((item) => item.id === complaint.assigned_official_id)?.full_name || (complaint.assigned_official_id ? "Account not in active directory" : "Department only")}</dd></div>}
        {isOfficial && <div><dt>Assignment access</dt><dd>{complaint.assigned_to_viewer ? "Assigned to your account" : "Authorized department work"}</dd></div>}
        <div><dt>Routing</dt><dd>{complaint.awaiting_department_review ? "Awaiting department review" : complaint.routing_review_required ? "Admin review needed" : complaint.department ? "Routed" : "Awaiting assignment"}</dd></div>
        {complaint.location?.coordinates?.length === 2 && <div><dt>Location</dt><dd>{complaint.location.coordinates[1].toFixed(5)}, {complaint.location.coordinates[0].toFixed(5)}</dd></div>}
        <div><dt>Report date</dt><dd>{complaint.created_at ? new Date(complaint.created_at).toLocaleString() : "Date unavailable"}</dd></div>
      </dl></div>
      {complaint.images?.length > 0 && <section className="detail-subsection" aria-labelledby="complaint-images-title"><h4 id="complaint-images-title">Attached images</h4><div className="detail-evidence-grid">{complaint.images.map((image) => <figure key={image.id}><a href={`${apiBase}${image.url}`} aria-label="Open protected complaint evidence image"><img crossOrigin="use-credentials" src={`${apiBase}${image.url}`} alt={`Attached evidence for ${complaint.category || "this complaint"}`} loading="lazy" /></a><figcaption>{image.width} Ãƒâ€” {image.height} Ã‚Â· {(image.byte_size / 1024).toFixed(0)} KB</figcaption></figure>)}</div><p className="detail-help">Evidence is served through NODALÃ¢â‚¬â„¢s complaint access check.</p></section>}
      {isOfficial && complaint.status === "resolution_submitted" && <div className="official-review-notice" role="status"><Clock3 size={17} /><span><strong>Resolution submitted</strong><small>Your submission is awaiting administrator review. You cannot approve or resolve it yourself.</small></span></div>}
      {complaint.assignment_history?.length > 0 && <section className="detail-subsection" aria-labelledby="assignment-history-title"><h4 id="assignment-history-title">Department assignment history</h4><ol className="detail-history">{complaint.assignment_history.map((entry, index) => <li key={`${entry.timestamp || index}-${index}`}><strong>{entry.previous_department || "No previous department"} to {entry.department}</strong><time>{entry.timestamp ? new Date(entry.timestamp).toLocaleString() : "Time unavailable"}</time>{entry.reason && isAdmin && <p>{cleanSyntheticText(entry.reason)}</p>}</li>)}</ol></section>}
      <section className="detail-subsection" aria-labelledby="status-timeline-title"><h4 id="status-timeline-title">Status timeline</h4>{complaint.status_history?.length ? <ol className="detail-history">{complaint.status_history.map((event, index) => <li key={`${event.created_at || index}-${index}`}><strong>{cleanSyntheticText(event.action || event.status || "update").replaceAll("_", " ")}</strong><time>{event.created_at ? new Date(event.created_at).toLocaleString() : "Time unavailable"}</time><span className="detail-actor">{event.actor_role || "System"}</span>{event.note && !((isCitizen || isOfficial) && isInternalRoutingEvent(event)) && <p>{cleanSyntheticText(event.note)}</p>}{event.evidence?.length > 0 && <ul className="detail-evidence-references">{event.evidence.map((reference, evidenceIndex) => { const href = safeEvidenceUrl(reference); return <li key={`${evidenceIndex}-${reference}`}>{href ? <a href={href} target="_blank" rel="noopener noreferrer">Open evidence reference</a> : isAdmin ? <span>Evidence reference: {cleanSyntheticText(reference)}</span> : <span>Supporting evidence recorded</span>}</li>; })}</ul>}</li>)}</ol> : <p className="empty-note">No status updates have been recorded.</p>}</section>
      {isAdmin && complaint.status === "resolution_submitted" && complaint.data_quality !== "demo_sample_unverified" && <section className="detail-subsection admin-resolution-review" aria-labelledby="resolution-review-title"><h4 id="resolution-review-title">Resolution review</h4><p>Review the officialÃ¢â‚¬â„¢s notes and evidence in the timeline above. Your decision and reason will be added to complaint history.</p><label>Administrator decision notes<textarea required maxLength={2000} rows={3} value={adminReviewNotes} onChange={(event) => setAdminReviewNotes(event.target.value)} /></label><label>Evidence references for approval<small>Pre-filled from the officialÃ¢â‚¬â„¢s submission; confirm or edit before approving.</small><textarea maxLength={10000} rows={3} value={adminReviewEvidence} onChange={(event) => setAdminReviewEvidence(event.target.value)} /></label>{adminReviewError && <p role="alert" className="form-error">{adminReviewError}</p>}<div className="button-row"><button type="button" className="button button--forest button--small" disabled={actionBusy} onClick={() => { const notes = adminReviewNotes.trim(); const evidence = adminReviewEvidence.split(/\r?\n/).map((item) => item.trim()).filter(Boolean); if (!notes) { setAdminReviewError("Add administrator review notes before deciding."); return; } if (!evidence.length) { setAdminReviewError("At least one supporting evidence reference is required to approve a resolution."); return; } setAdminReviewError(""); onAdminReview(complaint._id, "approve", notes, evidence); }}>Approve resolution</button><button type="button" className="button button--reject button--small" disabled={actionBusy} onClick={() => { const notes = adminReviewNotes.trim(); if (!notes) { setAdminReviewError("Add a reason before rejecting this resolution."); return; } setAdminReviewError(""); onAdminReview(complaint._id, "reject", notes, []); }}>Reject and return to official</button></div></section>}
      {isOfficial && ["assigned", "in_progress"].includes(complaint.status) && complaint.data_quality !== "demo_sample_unverified" && <form className="official-action-form" onSubmit={async (event) => { event.preventDefault(); const resolving = complaint.status === "in_progress"; const evidence = officialEvidence.split(/\r?\n/).map((item) => item.trim()).filter(Boolean); setOfficialError(""); if (resolving && !officialNotes.trim()) { setOfficialError("Add meaningful resolution notes before submitting."); return; } if (resolving && !evidence.length) { setOfficialError("Add at least one supporting evidence reference."); return; } const saved = await onOfficialAction(complaint._id, resolving ? "resolution_submitted" : "in_progress", { notes: officialNotes.trim(), evidence }); if (saved) { setOfficialNotes(""); setOfficialEvidence(""); } }}><div className="official-action-form__heading"><span>Next permitted action</span><span className={`status-tag status-${complaint.status}`}>Current status: {complaint.status.replaceAll("_", " ")}</span></div><h4>{complaint.status === "assigned" ? "Begin work" : "Submit resolution for review"}</h4><p>{complaint.status === "assigned" ? "Add an optional progress note before moving this report to in progress." : "A meaningful resolution note and at least one evidence reference are required. An administrator reviews submitted resolutions."}</p><label htmlFor="official-progress-note">{complaint.status === "assigned" ? "Progress note (optional)" : "Resolution notes"}<textarea id="official-progress-note" required={complaint.status === "in_progress"} maxLength={2000} rows={4} value={officialNotes} onChange={(event) => setOfficialNotes(event.target.value)} /></label>{complaint.status === "in_progress" && <label htmlFor="official-evidence">Supporting evidence references <small>Enter one URL or reference per line.</small><textarea id="official-evidence" required maxLength={10000} rows={3} value={officialEvidence} onChange={(event) => setOfficialEvidence(event.target.value)} /></label>}{officialError && <p role="alert" className="form-error">{officialError}</p>}<button className="button button--forest" disabled={actionBusy}>{actionBusy ? "Saving updateÃ¢â‚¬Â¦" : complaint.status === "assigned" ? "Start work" : "Submit resolution"}</button></form>}
      {isCitizen && complaint.status === "resolved" && <form className="dispute-form" onSubmit={onDispute}><h4>Request a review</h4><p>If the resolution is incorrect, explain what remains unresolved. An administrator will review your request.</p><label htmlFor="dispute-note">Why should this resolution be reopened?</label><textarea id="dispute-note" required maxLength={2000} rows={4} value={disputeNote} onChange={(event) => onDisputeNoteChange(event.target.value)} />{error && <p role="alert" className="form-error">{error}</p>}<button className="button button--outline" disabled={submittingDispute}>{submittingDispute ? "Sending requestÃ¢â‚¬Â¦" : "Dispute resolution and request reopening"}</button></form>}
    </>}
  </section>;
}

function Dashboard({ user, onLogout, onUserUpdated }) {
  const [complaints, setComplaints] = useState([]);
  const [hotspots, setHotspots] = useState([]);
  const [adminOverview, setAdminOverview] = useState(null);
  const [officials, setOfficials] = useState([]);
  const [registryDepartments, setRegistryDepartments] = useState([]);
  const [assignments, setAssignments] = useState({});
  const [mapCityId, setMapCityId] = useState("bengaluru");
  const [filters, setFilters] = useState({ status: "", priority: "", department: "", category: "" });
  const [workSort, setWorkSort] = useState("newest");
  const [description, setDescription] = useState("");
  const [category, setCategory] = useState("");
  const [imageFile, setImageFile] = useState(null);
  const [imagePreview, setImagePreview] = useState("");
  const [imageAnalysis, setImageAnalysis] = useState(null);
  const [analysisFile, setAnalysisFile] = useState(null);
  const [analyzingImage, setAnalyzingImage] = useState(false);
  const [picked, setPicked] = useState(null);
  const [latitude, setLatitude] = useState("");
  const [longitude, setLongitude] = useState("");
  const [detail, setDetail] = useState(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [disputeNote, setDisputeNote] = useState("");
  const [submittingDispute, setSubmittingDispute] = useState(false);
  const [actionBusy, setActionBusy] = useState(false);
  const [error, setError] = useState("");
  const [loadError, setLoadError] = useState("");
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);
  const [loading, setLoading] = useState(true);
  const load = useCallback(async () => {
    setLoading(true);
    try {
      const [items, areas, verifiedOfficials, registry, overview] = await Promise.all([
        request("/complaints"), request("/hotspots"),
        user.role === "admin" ? request("/admin/officials") : Promise.resolve([]),
        user.role === "admin" ? request("/admin/departments") : Promise.resolve([]),
        user.role === "admin" ? request("/admin/overview") : Promise.resolve(null),
      ]);
      setComplaints(items); setHotspots(areas); setOfficials(verifiedOfficials); setRegistryDepartments(registry);
      setAdminOverview(overview);
    }
    catch (err) { setError(err.message); }
    finally { setLoading(false); }
  }, [user.role]);
  useEffect(() => {
    let alive = true;
    Promise.all([
      request("/complaints"), request("/hotspots"),
      user.role === "admin" ? request("/admin/officials") : Promise.resolve([]),
      user.role === "admin" ? request("/admin/departments") : Promise.resolve([]),
      user.role === "admin" ? request("/admin/overview") : Promise.resolve(null),
    ]).then(([items, areas, verifiedOfficials, registry, overview]) => {
      if (alive) { setComplaints(items); setHotspots(areas); setOfficials(verifiedOfficials); setRegistryDepartments(registry); setAdminOverview(overview); }
    }).catch((err) => { if (alive) { setLoadError(err.message); setError(err.message); } }).finally(() => { if (alive) setLoading(false); });
    return () => { alive = false; };
  }, [user.role]);
  useEffect(() => () => { if (imagePreview) URL.revokeObjectURL(imagePreview); }, [imagePreview]);
  const active = useMemo(() => complaints.filter((row) => !["resolved", "disputed"].includes(row.status)), [complaints]);
  const departments = useMemo(() => [...new Set([...complaints.map((row) => row.department).filter(Boolean), ...(user.department ? [user.department] : [])])].sort(), [complaints, user.department]);
  const filteredComplaints = useMemo(() => complaints.filter((row) =>
    (!filters.status || row.status === filters.status) &&
    (!filters.priority || row.priority === filters.priority) &&
    (!filters.category || row.category === filters.category) &&
    (!filters.department || row.department === filters.department)), [complaints, filters]);
  const officialWorklist = useMemo(() => {
    const items = [...filteredComplaints];
    const dateValue = (row) => new Date(row.created_at || 0).getTime() || 0;
    if (workSort === "oldest") items.sort((a, b) => dateValue(a) - dateValue(b));
    else if (workSort === "priority") {
      const rank = { high: 0, medium: 1, low: 2 };
      items.sort((a, b) => (rank[a.priority] ?? 3) - (rank[b.priority] ?? 3) || dateValue(b) - dateValue(a));
    } else items.sort((a, b) => dateValue(b) - dateValue(a));
    return items;
  }, [filteredComplaints, workSort]);
  function pickLocation(location) {
    setPicked(location);
    setLatitude(location.lat.toFixed(6));
    setLongitude(location.lng.toFixed(6));
  }
  function applyCoordinates() {
    const lat = Number(latitude);
    const lng = Number(longitude);
    if (!latitude.trim() || !longitude.trim() || !Number.isFinite(lat) || !Number.isFinite(lng) ||
      lat < -90 || lat > 90 || lng < -180 || lng > 180) {
      setError("Enter a valid latitude from -90 to 90 and longitude from -180 to 180.");
      return;
    }
    setError("");
    setPicked({ lat, lng });
  }
  async function openComplaintDetails(id) {
    setDetail(null); setDetailError(""); setDisputeNote(""); setDetailLoading(true);
    try { setDetail(await request(`/complaints/${id}`)); }
    catch (err) { setDetailError(err.message); }
    finally { setDetailLoading(false); }
  }
  async function submit(event) {
    event.preventDefault(); setError(""); setNotice("");
    if (!picked) { setError("Choose a location on the map first."); return; }
    if (imageFile && analysisFile !== imageFile) { setError("Analyze the selected image before submitting the report."); return; }
    setBusy(true);
    try {
      const body = imageFile ? new FormData() : { description, category, lat: picked.lat, lng: picked.lng };
      if (imageFile) {
        body.append("description", description); body.append("category", category);
        body.append("lat", String(picked.lat)); body.append("lng", String(picked.lng)); body.append("image", imageFile);
      }
      const result = await request("/complaints", { method: "POST", body });
      setNotice(`Report received Ã‚Â· ${result.category} Ã‚Â· ${result.priority} priority`);
      setDescription(""); setCategory(""); setPicked(null); setLatitude(""); setLongitude(""); selectReportImage(null); await load();
    }
    catch (err) { setError(err.message); }
    finally { setBusy(false); }
  }
  async function analyzeReportImage() {
    if (!imageFile) return;
    setAnalyzingImage(true); setError(""); setImageAnalysis(null); setAnalysisFile(null);
    try {
      const body = new FormData(); body.append("image", imageFile);
      const result = await request("/vision/predict", { method: "POST", body });
      setImageAnalysis(result); setAnalysisFile(imageFile);
    } catch (err) { setError(err.message); }
    finally { setAnalyzingImage(false); }
  }
  function selectReportImage(file) {
    setError(""); setImagePreview(file ? URL.createObjectURL(file) : "");
    setImageFile(file || null); setImageAnalysis(null); setAnalysisFile(null);
  }
  async function transition(id, status, supplied = {}) {
    const complaint = complaints.find((row) => row._id === id);
    if (complaint?.data_quality === "demo_sample_unverified") {
      setError("Demonstration/sample complaints are read-only."); return;
    }
    const needsResolution = ["resolution_submitted", "resolved"].includes(status);
    const needsNote = needsResolution || status === "reopening_requested";
    const notes = supplied.notes ?? (needsNote ? window.prompt(status === "reopening_requested" ? "Why should this resolution be reopened?" : "Add resolution or review notes:") : "");
    if (needsNote && !notes?.trim()) return;
    const evidence = supplied.evidence ?? (needsResolution ? window.prompt("Add supporting evidence reference (URL or reference):") : null);
    if (needsResolution && !(Array.isArray(evidence) ? evidence.some((item) => item.trim()) : evidence?.trim())) return false;
    setActionBusy(true);
    try {
      const updated = await request(`/complaints/${id}/transition`, { method: "POST", body: { status, notes, evidence: Array.isArray(evidence) ? evidence : evidence ? [evidence.trim()] : [] } });
      setNotice(`Complaint status updated to ${status.replaceAll("_", " ")}.`);
      if (detail?._id === id) setDetail(updated);
      await load();
      return true;
    }
    catch (err) { setError(err.message); return false; }
    finally { setActionBusy(false); }
  }
  async function submitDispute(event) {
    event.preventDefault();
    if (!detail || !disputeNote.trim()) { setDetailError("Add a note explaining why the resolution should be reopened."); return; }
    setSubmittingDispute(true); setDetailError("");
    const changed = await transition(detail._id, "reopening_requested", { notes: disputeNote.trim() });
    if (changed) setDisputeNote("");
    setSubmittingDispute(false);
  }
  async function assignComplaint(id) {
    const values = assignments[id] || {};
    if (!values.department_id) { setError("Choose an active registry department before assigning this complaint."); return; }
    try {
      await request(`/complaints/${id}/assign`, { method: "POST", body: { department_id: values.department_id,
        official_id: values.official_id || undefined, reason: values.reason || "" } });
      setNotice("Complaint assigned to the selected department."); await load();
    } catch (err) { setError(err.message); }
  }
  async function reviewResolution(id, decision, notes, evidence) {
    const row = complaints.find((item) => item._id === id);
    if (!row || row.data_quality === "demo_sample_unverified" || row.status !== "resolution_submitted") {
      setError("Only a resident report with a submitted resolution can be reviewed here."); return false;
    }
    const status = decision === "approve" ? "resolved" : "in_progress";
    return transition(id, status, {
      notes: `Resolution ${decision === "approve" ? "approved" : "rejected"} by administrator: ${notes}`,
      evidence,
    });
  }
  const isCitizen = user.role === "citizen";
  const isAdmin = user.role === "admin";
  const isOfficial = user.role === "official";
  const selectedMapCity = MAP_CITIES.find((city) => city.id === mapCityId) || MAP_CITIES[0];
  return <main id="top" className="dashboard-page">
    <header className="app-bar page-gutter"><SiteMark /><nav className="dashboard-nav">{isCitizen && <a href="#my-reports">My reports</a>}{isOfficial && <a href="#assigned-work">Assigned work</a>}{isAdmin && <><a href="#complaint-management">Complaints</a><a href="#resolution-review">Resolutions</a></>}<a href="#map-board">City map</a>{isAdmin && <><a href="#admin-review">Verification</a><a href="#department-management">Departments</a></>}{isCitizen ? <a href="#account-area">Account &amp; access</a> : <a href="#profile">Profile</a>}</nav><div className="account-menu"><span className="account-avatar">{user.full_name?.slice(0, 1).toUpperCase()}</span><span className="account-label">{user.full_name}<small>{user.role}{user.department ? ` Ã‚Â· ${user.department}` : ""}</small></span><button className="icon-button" title="Sign out" onClick={onLogout}><LogOut size={17} /></button></div></header>
    <div className="dashboard-inner page-gutter">
      <div className="dashboard-heading"><div><span className="eyebrow">NODAL CIVIC Ã‚Â· BENGALURU</span><h1>{isCitizen ? "Your neighbourhood, in view." : isOfficial ? "Department workbench." : "Administrator workspace."}</h1><p>{isCitizen ? "Report a local concern and keep track of the issues you have raised." : isOfficial ? `Verified operations access Ã‚Â· ${user.department || "Department not set"}` : "Review complaints, access requests and resolution decisions."}</p></div></div>
      {isAdmin ? <AdminOverviewPanel overview={adminOverview} loading={loading} onRefresh={load} /> : isOfficial ? <OfficialWorkSummary complaints={complaints} loading={loading} error={loadError} /> : <div className="dashboard-stats"><Stat value={complaints.length} label="Your reports" icon={MapPinned} /><Stat value={active.length} label="Open for attention" icon={Clock3} /><Stat value={active.filter((row) => row.priority === "high").length} label="High priority" icon={CircleAlert} /><Stat value={hotspots.length} label="Platform hotspot clusters" icon={Sparkles} /></div>}
      <div className="legacy-notice"><CircleAlert size={16} /><span>Some older database records are demonstration/sample data and have not been verified as real civic reports.</span></div>
      {(error || notice) && <div role={error ? "alert" : "status"} className={error ? "form-error" : "form-success"}>{error || notice}</div>}
      <section id="workbench" className="workspace-grid">
      <div id="map-board" className="workspace-map"><div className="panel-heading map-panel-heading"><div><span className="eyebrow">Neighbourhood signals</span><h2>Map of reports</h2></div><CityMapSelector value={mapCityId} onChange={setMapCityId} /></div><div className="map-dashboard"><CityMap complaints={complaints} picked={picked} onPick={isCitizen ? pickLocation : undefined} center={selectedMapCity.center} zoom={selectedMapCity.zoom} cityName={selectedMapCity.name} /></div><div className="map-help"><MapPin size={15} /> {isCitizen ? picked ? `Selected ${picked.lat.toFixed(4)}, ${picked.lng.toFixed(4)} / click to adjust` : "Click the map to place your report" : "Map points reflect reports visible to your account"} Map view: {selectedMapCity.name}; city selection does not filter complaint records.</div></div>
        {isCitizen ? <aside className="report-panel"><span className="eyebrow">A concern close to home</span><h2>Make a report</h2><details className="report-disclosure"><summary><span><strong>Start a report</strong><small>Category, description and location required</small></span><ChevronRight size={18} aria-hidden="true" /></summary><form onSubmit={submit}><label>Issue category<select required value={category} onChange={(event) => setCategory(event.target.value)}><option value="">Choose a category</option>{CATEGORIES.map(([value, label]) => <option value={value} key={value}>{label}</option>)}</select></label><label>Description<textarea required minLength={8} maxLength={2000} rows={5} placeholder="What is happening, and what should the civic team know?" value={description} onChange={(event) => setDescription(event.target.value)} /></label><div className="selected-location"><MapPin size={15} />{picked ? `${picked.lat.toFixed(4)}, ${picked.lng.toFixed(4)}` : "Choose a point on the map"}</div><fieldset className="coordinate-fields"><legend>Or enter coordinates</legend><label>Latitude<input inputMode="decimal" aria-label="Latitude" value={latitude} onChange={(event) => setLatitude(event.target.value)} placeholder="12.9716" /></label><label>Longitude<input inputMode="decimal" aria-label="Longitude" value={longitude} onChange={(event) => setLongitude(event.target.value)} placeholder="77.5946" /></label><button type="button" className="button button--outline button--small" onClick={applyCoordinates}>Use coordinates</button></fieldset>{isCitizen && <div className="report-image-assistance"><div className="section-row"><div><span className="eyebrow">Optional image assistance</span><h2>Review a photo before reporting</h2></div></div><p>ImageNet is general image recognition, not a civic issue detector. Predictions are shown for your review only; they never select a category or submit a complaint. Choose the report category yourself in the form above.</p><div className="verification-fields"><label>Attach a JPEG, PNG or WebP image (maximum 5 MB)<input type="file" accept="image/jpeg,image/png,image/webp" onChange={(event) => { const file = event.target.files?.[0]; if (!file) { selectReportImage(null); return; } if (!file.type.match(/^image\/(jpeg|png|webp)$/)) { setError("Choose a JPEG, PNG or WebP image."); event.target.value = ""; return; } if (file.size > 5 * 1024 * 1024) { setError("Image is too large. Maximum size is 5 MB."); event.target.value = ""; return; } selectReportImage(file); }} /></label>{imageFile && <><p>{imageFile.name} Ã‚Â· {(imageFile.size / 1024).toFixed(0)} KB</p>{imagePreview && <img src={imagePreview} alt="Selected complaint evidence preview" style={{ maxWidth: "min(100%, 360px)", maxHeight: 240, objectFit: "contain", borderRadius: 12 }} />}<button type="button" className="button button--forest button--small" disabled={analyzingImage} onClick={analyzeReportImage}>{analyzingImage ? "Analysing imageÃ¢â‚¬Â¦" : imageAnalysis ? "Analyse again" : "Analyse image"}</button><button type="button" className="button button--outline button--small" onClick={() => selectReportImage(null)}>Remove image</button></>}{imageAnalysis && <div className="vision-result"><p><strong>{imageAnalysis.model}</strong> Ã‚Â· {imageAnalysis.warning}</p>{imageAnalysis.predictions.map((item) => { const mapped = item.label.toLowerCase().replaceAll(" ", "_"); const canSuggest = imageAnalysis.mode === "civic" && CATEGORIES.some(([value]) => value === mapped); return <div className="pred" key={item.label}><span>{item.label}</span><strong>{(item.confidence * 100).toFixed(1)}%</strong>{canSuggest && <button type="button" className="link-action" onClick={() => setCategory(mapped)}>Use as report category</button>}</div>; })}{imageAnalysis.mode === "demo" && <p>This output describes general objects. It does not identify or verify a civic issue.</p>}</div>}</div></div>}{error && <p className="form-error">{error}</p>}{notice && <p className="form-success"><Check size={15} />{notice}</p>}<button className="button button--terracotta button--wide" disabled={busy}>{busy ? "SendingÃ¢â‚¬Â¦" : "Submit report"}<ArrowUpRight size={16} /></button></form></details></aside> : <aside className="insight-panel"><span className="eyebrow">Areas of attention</span><h2>Patterns worth a closer look.</h2><p>Map circles group nearby open reports. They are exploratory signals, not official findings or department assignments.</p><div className="hotspot-list">{hotspots.slice(0, 4).map((item) => <div key={item.cluster_id}><span className="hotspot-number">{item.count}</span><span>{item.top_category}<small>{item.high_priority} high priority</small></span></div>)}{!hotspots.length && <p className="empty-note">No clustered areas in the current map view.</p>}</div></aside>}
      </section>


      {isAdmin && <div id="admin-review"><AdminVerificationQueue /></div>}
      {isAdmin && <div id="department-management"><AdminDepartmentManager /></div>}

      {!isOfficial &&       <section id={isCitizen ? "my-reports" : isOfficial ? "assigned-work" : "complaint-management"} className="complaints-section"><div className="section-row"><div><span className="eyebrow">A clear record</span><h2>{isCitizen ? "Your reports" : isOfficial ? "Assigned reports" : "Complaint management"}</h2></div><button className="button button--outline button--small" onClick={load}>Refresh list</button></div><div className="filter-bar">{(isCitizen || isAdmin) && <label>Category<select value={filters.category} onChange={(event) => setFilters({ ...filters, category: event.target.value })}><option value="">All categories</option>{(isAdmin ? ADMIN_CATEGORIES : CATEGORIES).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>}<label>Status<select value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })}><option value="">All statuses</option>{[...new Set(complaints.map((row) => row.status).filter(Boolean))].sort().map((status) => <option key={status} value={status}>{status.replaceAll("_", " ")}</option>)}</select></label><label>Priority<select value={filters.priority} onChange={(event) => setFilters({ ...filters, priority: event.target.value })}><option value="">All priorities</option>{["high", "medium", "low"].map((value) => <option key={value}>{value}</option>)}</select></label>{(isAdmin || isOfficial) && <label>Department<select value={filters.department} onChange={(event) => setFilters({ ...filters, department: event.target.value })}><option value="">All departments</option>{departments.map((department) => <option key={department} value={department}>{department}</option>)}</select></label>}{isAdmin && <label>Sort by<select value={workSort} onChange={(event) => setWorkSort(event.target.value)}><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="priority">Highest priority</option></select></label>}<button className="button button--outline button--small" onClick={() => setFilters({ status: "", priority: "", department: "", category: "" })}>Clear filters</button></div>{isCitizen ? <CitizenComplaintCards complaints={filteredComplaints} loading={loading} error={loadError} onOpen={openComplaintDetails} /> : isAdmin ? (filteredComplaints.length ? <div className="admin-complaint-grid">{officialWorklist.map((row) => <AdminComplaintCard key={row._id} complaint={row} officials={officials} onOpen={openComplaintDetails} />)}</div> : loading ? <div className="empty-state"><h3>Loading complaints...</h3><p>Fetching the administrator worklist.</p></div> : <div className="empty-state"><Leaf size={23} /><h3>No complaints match these filters.</h3><p>Adjust a filter or refresh the worklist.</p></div>) : loading ? <div className="empty-state"><h3>Loading reports...</h3><p>Fetching reports and routing details.</p></div> : <div className="empty-state"><Leaf size={23} /><h3>No reports match these filters.</h3><p>{isCitizen ? "Your submissions and updates will appear here." : "Try clearing a filter or refresh the work list."}</p></div>}</section>}
      {isOfficial && <section id="assigned-work" className="complaints-section official-work-section" aria-labelledby="official-work-title"><div className="section-row"><div><span className="eyebrow">Verified department workspace</span><h2 id="official-work-title">Complaint workload</h2><p className="detail-help">This list is limited by your individual assignment and verified department access.</p></div><button className="button button--outline button--small" onClick={load} disabled={loading}>{loading ? "RefreshingÃ¢â‚¬Â¦" : "Refresh work"}</button></div><div className="filter-bar"><label>Status<select value={filters.status} onChange={(event) => setFilters({ ...filters, status: event.target.value })}><option value="">All statuses</option>{[...new Set(complaints.map((row) => row.status).filter(Boolean))].sort().map((status) => <option key={status} value={status}>{status.replaceAll("_", " ")}</option>)}</select></label><label>Category<select value={filters.category} onChange={(event) => setFilters({ ...filters, category: event.target.value })}><option value="">All categories</option>{[...new Set(complaints.map((row) => row.category).filter(Boolean))].sort().map((value) => <option key={value} value={value}>{value.replaceAll("_", " ")}</option>)}</select></label><label>Priority<select value={filters.priority} onChange={(event) => setFilters({ ...filters, priority: event.target.value })}><option value="">All priorities</option>{["high", "medium", "low"].map((value) => <option key={value}>{value}</option>)}</select></label>{departments.length > 1 && <label>Department<select value={filters.department} onChange={(event) => setFilters({ ...filters, department: event.target.value })}><option value="">All authorized departments</option>{departments.map((department) => <option key={department} value={department}>{department}</option>)}</select></label>}<label>Sort by<select value={workSort} onChange={(event) => setWorkSort(event.target.value)}><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="priority">Highest priority</option></select></label><button className="button button--outline button--small" onClick={() => setFilters({ status: "", priority: "", department: "", category: "" })}>Clear filters</button></div>{loading && !complaints.length ? <div className="empty-state" role="status"><Clock3 size={22} /><h3>Loading authorized work</h3><p>Fetching complaints available to your account.</p></div> : loadError && !complaints.length ? <div className="empty-state" role="alert"><CircleAlert size={22} /><h3>Worklist could not be loaded</h3><p>{loadError}</p></div> : officialWorklist.length ? <div className="official-work-grid">{officialWorklist.map((row) => <OfficialWorkCard key={row._id} complaint={row} department={user.department} onOpen={openComplaintDetails} />)}</div> : <div className="empty-state"><Leaf size={23} /><h3>No authorized reports match these filters.</h3><p>Clear a filter or refresh your worklist. New assignments will appear here when authorized.</p></div>}</section>}
      {(isCitizen || isOfficial || isAdmin) && <ComplaintDetailPanel key={detail?._id || "complaint-detail"} complaint={detail} loading={detailLoading} error={detailError} onClose={() => setDetail(null)} isCitizen={isCitizen} isOfficial={isOfficial} isAdmin={isAdmin} officials={officials} onOfficialAction={transition} onAdminReview={reviewResolution} actionBusy={actionBusy} disputeNote={disputeNote} onDisputeNoteChange={setDisputeNote} onDispute={submitDispute} submittingDispute={submittingDispute} />}
      {isAdmin && <section className="complaints-section"><div className="section-row"><div><span className="eyebrow">Department routing</span><h2>Assign reports</h2><p className="routing-caution">Assignment updates the complaint lifecycle. A suggestion alone never assigns an official or changes status.</p></div></div><div className="request-list">{complaints.filter((row) => !row.data_quality).map((row) => { const value = assignments[row._id] || {}; const currentDepartment = registryDepartments.find((item) => item.name === row.department); const selectedId = value.department_id ?? row.department_id ?? row.suggested_department_id ?? ""; const keepOfficial = selectedId === row.department_id ? row.assigned_official_id || "" : ""; return <article className="request-card admin-management-card" key={`assignment-${row._id}`}><div className="request-person"><strong>{row.description}</strong><span>Status: {row.status?.replaceAll("_", " ")}</span><span>Suggested: {row.suggested_department_name || "No active mapping"}</span><span>Assigned: {row.department || "Not assigned"}</span>{row.assignment_history?.map((entry, index) => <span key={`${row._id}-assignment-${index}`}>Assignment {index + 1}: {entry.previous_department || "None"} to {entry.department} Ã‚Â· {entry.reason}</span>)}</div><div className="verification-fields"><label>Active registry department<select value={selectedId} onChange={(event) => setAssignments((old) => ({ ...old, [row._id]: { ...old[row._id], department_id: event.target.value } }))}><option value="">Choose department</option>{registryDepartments.filter((item) => item.active).map((department) => <option key={department.id} value={department.id}>{department.name}{department.id === row.suggested_department_id ? " Ã‚Â· suggested" : ""}</option>)}</select></label><label>Verified official<select value={value.official_id ?? keepOfficial} onChange={(event) => setAssignments((old) => ({ ...old, [row._id]: { ...old[row._id], official_id: event.target.value } }))}><option value="">Keep department only</option>{officials.filter((official) => official.department_id === selectedId || official.department === registryDepartments.find((dept) => dept.id === selectedId)?.name).map((official) => <option key={official.id} value={official.id}>{official.full_name} Ã‚Â· {official.department}</option>)}</select></label><label>Reason for override or reassignment<input maxLength={2000} value={value.reason || ""} onChange={(event) => setAssignments((old) => ({ ...old, [row._id]: { ...old[row._id], reason: event.target.value } }))} placeholder={row.routing_review_required ? "Required: explain department choice" : currentDepartment && selectedId === currentDepartment.id ? "Reason required only if changing department" : "Required when overriding or reassigning"} /></label><button className="button button--forest button--small" onClick={() => assignComplaint(row._id)}>Assign department</button></div></article>; })}{!complaints.some((row) => !row.data_quality) && <p className="empty-note">No resident reports available for assignment.</p>}</div></section>}
      {isAdmin && <section id="resolution-review" className="complaints-section"><div className="section-row"><div><span className="eyebrow">Status history</span><h2>Lifecycle updates</h2></div></div><div className="request-list">{complaints.map((row) => <article className="request-card admin-management-card" key={`history-${row._id}`}><div className="request-person"><strong>{complaintDescription(row)}</strong><div className="admin-complaint-card__badges">{isDemoComplaint(row) && <span className="demo-data-badge">Demo data</span>}<span className={`status-tag status-${row.status}`}>{row.status?.replaceAll("_", " ")}</span></div></div><div className="verification-fields">{row.status_history?.map((event, index) => <p key={`${row._id}-${index}`}><strong>{cleanSyntheticText(event.action || event.status)}</strong> Ã‚Â· {event.actor_role || "legacy"} Ã‚Â· {event.created_at ? new Date(event.created_at).toLocaleString() : "time unavailable"}{event.note ? ` Ã‚Â· ${cleanSyntheticText(event.note)}` : ""}</p>)}{isAdmin && ["submitted", "open"].includes(row.status) && <button className="button button--forest button--small" onClick={() => transition(row._id, "triaged")}>Triage report</button>}{isOfficial && row.status === "assigned" && <button className="button button--forest button--small" onClick={() => transition(row._id, "in_progress")}>Start work</button>}{isOfficial && row.status === "in_progress" && <button className="button button--forest button--small" onClick={() => transition(row._id, "resolution_submitted")}>Submit resolution</button>}{isAdmin && row.status === "resolution_submitted" && <button className="button button--forest button--small" onClick={() => openComplaintDetails(row._id)}>Review resolution</button>}{isAdmin && row.status === "reopening_requested" && <><button className="button button--forest button--small" onClick={() => transition(row._id, "in_progress")}>Reopen report</button><button className="button button--outline button--small" onClick={() => transition(row._id, "resolved")}>Keep resolution</button></>}{isCitizen && row.status === "resolved" && <button className="button button--outline button--small" onClick={() => transition(row._id, "reopening_requested")}>Dispute and request reopening</button>}</div></article>)}</div></section>}
      {isAdmin && complaints.some((row) => row.images?.length) && <section className="complaints-section"><div className="section-row"><div><span className="eyebrow">Private attachments</span><h2>Report images</h2></div></div><div className="request-list">{complaints.flatMap((row) => (row.images || []).map((image) => <article className="request-card" key={image.id}><div className="request-person"><strong>{complaintDescription(row)}</strong>{isDemoComplaint(row) && <span className="demo-data-badge">Demo data</span>}<span>{(image.byte_size / 1024).toFixed(0)} KB Ã‚Â· {image.width} Ãƒâ€” {image.height}</span></div><a className="button button--outline button--small" href={`${import.meta.env.VITE_API_BASE || "http://localhost:5000"}${image.url}`}>Download attached image</a></article>))}</div></section>}
      {isCitizen ? <div id="account-area" className="account-area" aria-labelledby="account-area-title">
        <div className="section-row account-area-heading"><div><span className="eyebrow">Account and access</span><h2 id="account-area-title">Your account</h2><p>Update your profile or submit an official access request for independent review.</p></div></div>
        <div className="account-area-grid"><ProfilePanel user={user} onUpdated={onUserUpdated} /><div id="official-access-request"><OfficialAccessRequest /></div></div>
      </div> : <ProfilePanel user={user} onUpdated={onUserUpdated} />}
      <footer className="dashboard-footer"><SiteMark /><span>Some older records are demonstrations, not verified civic reports.</span></footer>
    </div>
  </main>;
}

export default function App() {
  const [user, setUser] = useState(null);
  const [checking, setChecking] = useState(true);
  const [authMode, setAuthMode] = useState(null);
  const [overview, setOverview] = useState(null);
  const [hotspots, setHotspots] = useState([]);
  const [loadError, setLoadError] = useState("");
  useEffect(() => {
    let alive = true;
    refreshCsrf().catch(() => {});
    request("/auth/me").then((data) => { if (alive) setUser(data.user); }).catch((err) => { if (alive && err.status !== 401) setLoadError("The NODAL service is temporarily unavailable."); }).finally(() => { if (alive) setChecking(false); });
    request("/public/overview").then((data) => { if (alive) setOverview(data); }).catch(() => {});
    request("/hotspots").then((data) => { if (alive) setHotspots(data); }).catch(() => {});
    return () => { alive = false; };
  }, []);
  async function logout() {
    try { await request("/auth/logout", { method: "POST", body: {} }); } catch { /* server session can expire independently */ }
    setUser(null); setAuthMode(null); await refreshCsrf().catch(() => {});
  }
  function returnToLanding() {
    setAuthMode(null);
    window.scrollTo({ top: 0, behavior: "smooth" });
  }
  if (checking) return <div className="boot-screen"><SiteMark /><span>Finding your place in NODALÃ¢â‚¬Â¦</span></div>;
  if (user) return <Dashboard user={user} onLogout={logout} onUserUpdated={setUser} />;
  if (authMode) return <AuthPanel mode={authMode} setMode={setAuthMode} onBack={returnToLanding} onSuccess={setUser} />;
  return <><Landing overview={overview} hotspots={hotspots} onAuth={setAuthMode} />{loadError && <div className="toast-error"><CircleAlert size={15} />{loadError}</div>}</>;
}
