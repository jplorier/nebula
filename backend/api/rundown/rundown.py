import nebula
from nebula.enum import ObjectStatus, RunMode
from nebula.helpers.scheduling import (
    get_item_runs,
    get_pending_assets,
    parse_durations,
    parse_rundown_date,
)

from .models import RundownRequestModel, RundownResponseModel, RundownRow


async def get_rundown(request: RundownRequestModel) -> RundownResponseModel:
    """Get a rundown"""

    if not (channel := nebula.settings.get_playout_channel(request.id_channel)):
        raise nebula.BadRequestException(f"No such channel: {request.id_channel}")

    start_time = parse_rundown_date(request.date, channel)
    end_time = start_time + (3600 * 24)
    item_runs = await get_item_runs(request.id_channel, start_time, end_time)
    pending_assets = await get_pending_assets(channel.send_action)
    pskey = f"playout_status/{request.id_channel}"

    query = """
        SELECT
            e.id AS id_event,
            e.meta AS emeta,
            e.id_magic AS id_bin,
            i.id AS id_item,
            i.meta AS imeta,
            a.meta AS ameta
        FROM
            events AS e
        LEFT JOIN
            items AS i
        ON
            e.id_magic = i.id_bin
        LEFT JOIN
            assets AS a
        ON
            i.id_asset = a.id
        WHERE
            e.id_channel = $1 AND e.start >= $2 AND e.start < $3
        ORDER BY
            e.start ASC,
            i.position ASC,
            i.id ASC
    """

    rows: list[nebula.Event] = []

    last_event = None
    ts_broadcast = ts_scheduled = 0.0

    async for record in nebula.db.iterate(
        query, request.id_channel, start_time, end_time
    ):
        id_event = record["id_event"]
        id_item = record["id_item"]
        id_bin = record["id_bin"]
        emeta = record["emeta"] or {}
        imeta = record["imeta"] or {}
        ameta = record["ameta"] or {}

        if (last_event is None) or (id_event != last_event.id):
            row = RundownRow(
                id=id_event,
                type="event",
                row_number=len(rows),
                scheduled_time=emeta["start"],
                broadcast_time=emeta["start"],
                run_mode=emeta.get("run_mode", RunMode.RUN_AUTO),
                title=emeta.get("title"),
                subtitle=emeta.get("subtitle"),
                id_asset=emeta.get("id_asset"),
                id_bin=id_bin,
                meta=emeta,
            )

            ts_scheduled = row.scheduled_time

            if last_event and (not last_event.duration):
                ts_broadcast = 0

            if emeta.get("run_mode", 0):
                ts_broadcast = emeta["start"]

            last_event = row
            rows.append(row)

        if id_item is None:
            # TODO: append empty row?
            continue

        airstatus = 0
        if (runs := item_runs.get(id_item)) is not None:
            as_start, as_stop = runs
            ts_broadcast = as_start
            if as_stop:
                airstatus = ObjectStatus.AIRED
            else:
                airstatus = ObjectStatus.ONAIR

        # TODO
        # if rundown_event_asset:
        #     item.meta["rundown_event_asset"] = rundown_event_asset

        # Row status

        istatus = 0
        if not ameta:
            istatus = ObjectStatus.ONLINE
        elif airstatus:
            istatus = airstatus
        elif ameta.get("status") == ObjectStatus.OFFLINE:
            istatus = ObjectStatus.OFFLINE
        elif pskey not in ameta:
            istatus = ObjectStatus.REMOTE
        elif ameta[pskey]["status"] == ObjectStatus.OFFLINE:
            istatus = ObjectStatus.REMOTE
        elif ameta[pskey]["status"] == ObjectStatus.ONLINE:
            istatus = ObjectStatus.ONLINE
        elif ameta[pskey]["status"] == ObjectStatus.CORRUPTED:
            istatus = ObjectStatus.CORRUPTED
        else:
            istatus = ObjectStatus.UNKNOWN

        if ameta and ameta["id"] in pending_assets:
            transfer_progress = -1
        else:
            transfer_progress = None

        duration, mark_in, mark_out = parse_durations(ameta, imeta)

        # Append item to the result

        row = RundownRow(
            id=id_item,
            row_number=len(rows),
            type="item",
            scheduled_time=ts_scheduled,
            broadcast_time=ts_broadcast,
            run_mode=imeta.get("run_mode"),
            item_role=imeta.get("item_role"),
            title=imeta.get("title") or ameta.get("title"),
            subtitle=imeta.get("subtitle") or ameta.get("subtitle"),
            id_asset=imeta.get("id_asset"),
            id_bin=id_bin,
            duration=duration,
            status=istatus,
            transfer_progress=transfer_progress,
            asset_mtime=ameta.get("mtime", 0),
            mark_in=mark_in,
            mark_out=mark_out,
        )

        rows.append(row)

        # Update timestamps

        if row.run_mode != RunMode.RUN_SKIP:
            last_event.broadcast_time = ts_broadcast
            ts_scheduled += duration
            ts_broadcast += duration
            last_event.duration += duration

    return RundownResponseModel(rows=rows)
