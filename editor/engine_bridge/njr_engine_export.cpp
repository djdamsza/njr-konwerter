/*
 * NJR Konwerter — eksport biblioteki Engine DJ przez libdjinterop.
 * Wejście: ścieżka do pliku JSON (patrz engine_generator.py).
 * Wyjście: stdout JSON {"ok":true,...} lub stderr + kod != 0.
 */
#include <djinterop/djinterop.hpp>
#include <djinterop/engine/engine.hpp>

#include <nlohmann/json.hpp>

#include <chrono>
#include <cmath>
#include <fstream>
#include <iostream>
#include <map>
#include <optional>
#include <set>
#include <stdexcept>
#include <string>
#include <vector>

namespace e = djinterop::engine;
using json = nlohmann::json;

static std::optional<djinterop::musical_key> camelot_to_key(const std::string& raw)
{
    if (raw.empty()) return std::nullopt;
    static const std::map<std::string, djinterop::musical_key> m = {
        {"8B", djinterop::musical_key::c_major},   {"8A", djinterop::musical_key::a_minor},
        {"9B", djinterop::musical_key::g_major},   {"9A", djinterop::musical_key::e_minor},
        {"10B", djinterop::musical_key::d_major},  {"10A", djinterop::musical_key::b_minor},
        {"11B", djinterop::musical_key::a_major},  {"11A", djinterop::musical_key::f_sharp_minor},
        {"12B", djinterop::musical_key::e_major},  {"12A", djinterop::musical_key::d_flat_minor},
        {"1B", djinterop::musical_key::b_major},   {"1A", djinterop::musical_key::a_flat_minor},
        {"2B", djinterop::musical_key::f_sharp_major}, {"2A", djinterop::musical_key::e_flat_minor},
        {"3B", djinterop::musical_key::d_flat_major},  {"3A", djinterop::musical_key::b_flat_minor},
        {"4B", djinterop::musical_key::a_flat_major},  {"4A", djinterop::musical_key::f_minor},
        {"5B", djinterop::musical_key::e_flat_major},  {"5A", djinterop::musical_key::c_minor},
        {"6B", djinterop::musical_key::b_flat_major},  {"6A", djinterop::musical_key::g_minor},
        {"7B", djinterop::musical_key::f_major},       {"7A", djinterop::musical_key::d_minor},
    };
    auto it = m.find(raw);
    if (it != m.end()) return it->second;
    return std::nullopt;
}

static djinterop::pad_color pad_for_index(int idx)
{
    if (idx < 0 || idx >= 8) idx = 0;
    return e::standard_pad_colors::pads[static_cast<size_t>(idx)];
}

static void clear_database(djinterop::database& db)
{
    for (auto& pl : db.root_playlists()) db.remove_playlist(pl);
    for (auto& cr : db.root_crates()) db.remove_crate(cr);
    for (auto& tr : db.tracks()) db.remove_track(tr);
}

static djinterop::track_snapshot track_from_json(const json& jt, int sample_rate)
{
    djinterop::track_snapshot td;
    td.relative_path = std::nullopt;
    const std::string rel_path = jt.value("relative_path", "");
    if (!rel_path.empty()) {
        td.relative_path = rel_path;
    }
    td.title = jt.value("title", "");
    td.artist = jt.value("artist", "");
    td.album = jt.value("album", "");
    td.genre = jt.value("genre", "");
    if (jt.contains("comment")) {
        auto c = jt["comment"].get<std::string>();
        if (!c.empty()) td.comment = c;
    }
    td.publisher = std::nullopt;
    td.year = jt.value("year", 0);
    td.bpm = jt.value("bpm", 0.0);
    td.bitrate = jt.value("bitrate", 0);
    if (jt.contains("file_bytes")) {
        const auto fb = jt["file_bytes"].get<unsigned long long>();
        if (fb > 0) {
            td.file_bytes = fb;
        }
    }
    td.rating = jt.value("rating", 0);
    td.sample_rate = sample_rate;
    td.average_loudness = 0.5;

    const double duration_sec = jt.value("duration_sec", 0.0);
    if (duration_sec > 0) {
        td.duration = std::chrono::milliseconds(static_cast<long long>(duration_sec * 1000.0));
        td.sample_count = static_cast<unsigned long long>(duration_sec * sample_rate);
    }

    if (jt.contains("key_camelot")) {
        td.key = camelot_to_key(jt["key_camelot"].get<std::string>());
    }

    if (jt.contains("beatgrid") && jt["beatgrid"].is_array()) {
        for (const auto& bm : jt["beatgrid"]) {
            djinterop::beatgrid_marker m;
            m.index = bm.value("index", 0);
            m.sample_offset = bm.value("sample_offset", 0.0);
            td.beatgrid.push_back(m);
        }
    }

    if (jt.contains("hot_cues") && jt["hot_cues"].is_array()) {
        td.hot_cues.resize(8);
        for (const auto& hc : jt["hot_cues"]) {
            const int slot = hc.value("slot", -1);
            if (slot < 0 || slot >= 8) continue;
            djinterop::hot_cue cue;
            cue.label = hc.value("label", "Cue");
            cue.sample_offset = hc.value("sample_offset", 0.0);
            cue.color = pad_for_index(hc.value("pad", slot));
            td.hot_cues[static_cast<size_t>(slot)] = cue;
        }
    }

    if (jt.contains("loops") && jt["loops"].is_array()) {
        td.loops.resize(8);
        for (const auto& lp : jt["loops"]) {
            const int slot = lp.value("slot", -1);
            if (slot < 0 || slot >= 8) continue;
            djinterop::loop loop;
            loop.label = lp.value("label", "Loop");
            loop.start_sample_offset = lp.value("start_sample_offset", 0.0);
            loop.end_sample_offset = lp.value("end_sample_offset", 0.0);
            loop.color = pad_for_index(lp.value("pad", slot));
            td.loops[static_cast<size_t>(slot)] = loop;
        }
    }

    if (jt.contains("main_cue_offset")) {
        td.main_cue = jt["main_cue_offset"].get<double>();
    }

    return td;
}

static djinterop::track upsert_track(
    djinterop::database& db,
    const djinterop::track_snapshot& td,
    bool json_had_hot_cues,
    bool json_had_loops,
    bool json_had_beatgrid)
{
    const auto& rel = *td.relative_path;
    auto existing = db.tracks_by_relative_path(rel);
    if (!existing.empty()) {
        auto snap = td;
        if (!json_had_hot_cues) {
            snap.hot_cues = existing.front().hot_cues();
        } else if (snap.hot_cues.size() < 8) {
            snap.hot_cues.resize(8);
        }
        if (!json_had_loops) {
            snap.loops = existing.front().loops();
        } else if (snap.loops.size() < 8) {
            snap.loops.resize(8);
        }
        if (!json_had_beatgrid) {
            snap.beatgrid = existing.front().beatgrid();
        }
        existing.front().update(snap);
        return existing.front();
    }
    auto create_snap = td;
    if (create_snap.hot_cues.empty()) {
        create_snap.hot_cues.resize(8);
    } else if (create_snap.hot_cues.size() < 8) {
        create_snap.hot_cues.resize(8);
    }
    if (create_snap.loops.empty()) {
        create_snap.loops.resize(8);
    } else if (create_snap.loops.size() < 8) {
        create_snap.loops.resize(8);
    }
    return db.create_track(create_snap);
}

static djinterop::playlist upsert_root_playlist(
    djinterop::database& db,
    const std::string& name,
    bool replace_tracks)
{
    auto pl_opt = db.root_playlist_by_name(name);
    if (pl_opt) {
        if (replace_tracks) pl_opt->clear_tracks();
        return *pl_opt;
    }
    return db.create_root_playlist(name);
}

static void fill_playlist_tracks(
    djinterop::playlist& pl,
    const json& track_paths,
    const std::map<std::string, djinterop::track>& path_to_track)
{
    if (!track_paths.is_array()) return;
    std::set<std::string> seen;
    for (const auto& rp : track_paths) {
        const std::string rel = rp.get<std::string>();
        if (rel.empty() || !seen.insert(rel).second) continue;
        auto it = path_to_track.find(rel);
        if (it != path_to_track.end()) {
            try {
                pl.add_track_back(it->second);
            } catch (const std::exception&) {
                // Duplikat w playliście (merge / VDJ filter list) — pomiń.
            }
        }
    }
}

static djinterop::playlist upsert_child_playlist(
    djinterop::playlist& parent,
    const std::string& name,
    bool replace_tracks)
{
    auto pl_opt = parent.sub_playlist_by_name(name);
    if (pl_opt) {
        if (replace_tracks) pl_opt->clear_tracks();
        return *pl_opt;
    }
    return parent.create_sub_playlist(name);
}

static int cleanup_legacy_flat_vdj_playlists(djinterop::database& db)
{
    std::vector<djinterop::playlist> to_remove;
    for (const auto& pl : db.root_playlists()) {
        const std::string name = pl.name();
        if (name.rfind("VDJ / ", 0) == 0) {
            to_remove.push_back(pl);
        }
    }
    for (const auto& pl : to_remove) {
        db.remove_playlist(pl);
    }
    return static_cast<int>(to_remove.size());
}

static int prune_tracks_not_in_export(
    djinterop::database& db,
    const std::set<std::string>& export_paths)
{
    if (export_paths.empty()) return 0;
    std::vector<djinterop::track> to_remove;
    for (const auto& tr : db.tracks()) {
        const std::string rel = tr.relative_path();
        if (!rel.empty() && export_paths.find(rel) == export_paths.end()) {
            to_remove.push_back(tr);
        }
    }
    int removed = 0;
    for (const auto& tr : to_remove) {
        try {
            db.remove_track(tr);
            ++removed;
        } catch (const std::exception&) {
        }
    }
    return removed;
}

static void import_playlist_node(
    djinterop::database& db,
    djinterop::playlist* parent,
    const json& jp,
    bool merge,
    bool replace_playlist_tracks,
    const std::map<std::string, djinterop::track>& path_to_track,
    int& playlists_added,
    int& playlists_updated,
    int& playlists_skipped)
{
    try {
        std::string name = jp.value("name", "");
        if (name.empty()) return;

        djinterop::playlist pl = [&]() -> djinterop::playlist {
            if (parent) {
                return merge
                    ? upsert_child_playlist(*parent, name, replace_playlist_tracks)
                    : parent->create_sub_playlist(name);
            }
            return merge
                ? upsert_root_playlist(db, name, replace_playlist_tracks)
                : db.create_root_playlist(name);
        }();

        const bool had = parent
            ? parent->sub_playlist_by_name(name).has_value()
            : db.root_playlist_by_name(name).has_value();

        if (jp.contains("track_paths") && jp["track_paths"].is_array()) {
            fill_playlist_tracks(pl, jp["track_paths"], path_to_track);
        }

        if (jp.contains("children") && jp["children"].is_array()) {
            for (const auto& child : jp["children"]) {
                import_playlist_node(
                    db,
                    &pl,
                    child,
                    merge,
                    replace_playlist_tracks,
                    path_to_track,
                    playlists_added,
                    playlists_updated,
                    playlists_skipped);
            }
        }

        if (had) {
            ++playlists_updated;
        } else {
            ++playlists_added;
        }
    } catch (const std::exception&) {
        ++playlists_skipped;
    }
}

int main(int argc, char** argv)
{
    try {
        if (argc < 2) {
            std::cerr << "Usage: njr-engine-export <export.json>\n";
            return 2;
        }

        std::ifstream in(argv[1]);
        if (!in) throw std::runtime_error(std::string("Cannot open ") + argv[1]);
        json doc;
        in >> doc;

        const std::string engine_dir = doc.value("engine_dir", "");
        if (engine_dir.empty()) throw std::runtime_error("engine_dir required");

        const bool clear = doc.value("clear_existing", true);
        const bool merge = doc.value("merge_mode", false);
        const bool replace_playlist_tracks = doc.value("replace_playlist_tracks", true);
        const std::string playlist_prefix = doc.value("playlist_prefix", "");
        const bool cleanup_legacy_vdj = doc.value("cleanup_legacy_vdj_playlists", false);
        const bool prune_tracks = doc.value("prune_tracks_not_in_source", false);
        const int default_sr = doc.value("sample_rate", 44100);

        bool created = false;
        auto db = e::create_or_load_database(engine_dir, e::latest_schema, created);
        if (merge) {
            if (clear) {
                throw std::runtime_error("merge_mode cannot be used with clear_existing");
            }
        } else if (clear) {
            clear_database(db);
        }

        std::map<std::string, djinterop::track> path_to_track;
        std::set<std::string> export_paths;

        int tracks_added = 0;
        int tracks_updated = 0;
        int tracks_skipped = 0;
        if (doc.contains("tracks") && doc["tracks"].is_array()) {
            for (const auto& jt : doc["tracks"]) {
                try {
                    const int sr = jt.value("sample_rate", default_sr);
                    auto td = track_from_json(jt, sr);
                    if (!td.relative_path || td.relative_path->empty()) continue;
                    const std::string rel = *td.relative_path;
                    export_paths.insert(rel);
                    const bool json_had_hot_cues =
                        jt.contains("hot_cues") && jt["hot_cues"].is_array()
                        && !jt["hot_cues"].empty();
                    const bool json_had_loops =
                        jt.contains("loops") && jt["loops"].is_array()
                        && !jt["loops"].empty();
                    const bool json_had_beatgrid =
                        jt.contains("beatgrid") && jt["beatgrid"].is_array()
                        && !jt["beatgrid"].empty();
                    const bool exists = !db.tracks_by_relative_path(rel).empty();
                    djinterop::track tr = [&]() -> djinterop::track {
                        if (merge) {
                            return upsert_track(db, td, json_had_hot_cues, json_had_loops, json_had_beatgrid);
                        }
                        auto create_snap = td;
                        if (create_snap.hot_cues.empty()) {
                            create_snap.hot_cues.resize(8);
                        } else if (create_snap.hot_cues.size() < 8) {
                            create_snap.hot_cues.resize(8);
                        }
                        if (create_snap.loops.empty()) {
                            create_snap.loops.resize(8);
                        } else if (create_snap.loops.size() < 8) {
                            create_snap.loops.resize(8);
                        }
                        return db.create_track(create_snap);
                    }();
                    path_to_track.emplace(rel, tr);
                    if (exists) {
                        ++tracks_updated;
                    } else {
                        ++tracks_added;
                    }
                } catch (const std::exception&) {
                    ++tracks_skipped;
                }
            }
        }

        int playlists_added = 0;
        int playlists_updated = 0;
        int playlists_skipped = 0;
        int legacy_playlists_removed = 0;
        int tracks_pruned = 0;
        if (merge && cleanup_legacy_vdj) {
            legacy_playlists_removed = cleanup_legacy_flat_vdj_playlists(db);
        }
        if (doc.contains("playlists") && doc["playlists"].is_array()) {
            for (const auto& jp : doc["playlists"]) {
                std::string name = jp.value("name", "");
                if (!playlist_prefix.empty()) {
                    name = playlist_prefix + name;
                }
                json root = jp;
                if (!name.empty() && name != jp.value("name", "")) {
                    root = jp;
                    root["name"] = name;
                }
                import_playlist_node(
                    db,
                    nullptr,
                    root,
                    merge,
                    replace_playlist_tracks,
                    path_to_track,
                    playlists_added,
                    playlists_updated,
                    playlists_skipped);
            }
        }

        if (merge && prune_tracks) {
            tracks_pruned = prune_tracks_not_in_export(db, export_paths);
        }

        if (merge) {
            db.verify();
        }

        if (merge && cleanup_legacy_vdj) {
            legacy_playlists_removed += cleanup_legacy_flat_vdj_playlists(db);
        }

        json out;
        out["ok"] = true;
        out["created"] = created;
        out["merge_mode"] = merge;
        out["engine_dir"] = engine_dir;
        out["tracks_added"] = tracks_added;
        out["tracks_updated"] = tracks_updated;
        out["tracks_skipped"] = tracks_skipped;
        out["tracks_pruned"] = tracks_pruned;
        out["playlists_added"] = playlists_added;
        out["playlists_updated"] = playlists_updated;
        out["playlists_skipped"] = playlists_skipped;
        out["legacy_playlists_removed"] = legacy_playlists_removed;
        out["database_uuid"] = db.uuid();
        out["schema"] = db.version_name();
        std::cout << out.dump() << std::endl;
        return 0;
    } catch (const std::exception& ex) {
        json err;
        err["ok"] = false;
        err["error"] = ex.what();
        std::cerr << err.dump() << std::endl;
        return 1;
    }
}
