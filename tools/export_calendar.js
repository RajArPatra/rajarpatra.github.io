// Dump timed + all-day events from EventKit as JSON on stdout.
// Titles are included ONLY so the builder can collapse duplicate entries;
// build_week_load.py never writes them to disk. See tools/update_week_load.py.
ObjC.import('EventKit');
ObjC.import('Foundation');

function run(argv) {
  var store = $.EKEventStore.alloc.init;
  var done = false, granted = false;
  store.requestAccessToEntityTypeCompletion($.EKEntityTypeEvent, function (g) { granted = g; done = true; });
  var deadline = $.NSDate.dateWithTimeIntervalSinceNow(20);
  while (!done && $.NSDate.date.isLessThan(deadline)) {
    $.NSRunLoop.currentRunLoop.runModeBeforeDate($.NSDefaultRunLoopMode, $.NSDate.dateWithTimeIntervalSinceNow(0.1));
  }
  if (!granted) { console.log(JSON.stringify({ error: 'NO_CALENDAR_ACCESS' })); return; }

  var inFmt = $.NSDateFormatter.alloc.init;
  inFmt.dateFormat = 'yyyy-MM-dd HH:mm:ss';
  var outFmt = $.NSDateFormatter.alloc.init;
  outFmt.dateFormat = "yyyy-MM-dd'T'HH:mm:ss";

  var from = inFmt.dateFromString(argv[0] + ' 00:00:00');
  var to   = inFmt.dateFromString(argv[1] + ' 00:00:00');

  var rows = [], cur = from;
  while (cur.isLessThan(to)) {                       // EventKit caps a predicate's span
    var nxt = cur.dateByAddingTimeInterval(60 * 60 * 24 * 80);
    if (to.isLessThan(nxt)) nxt = to;
    var evs = store.eventsMatchingPredicate(
      store.predicateForEventsWithStartDateEndDateCalendars(cur, nxt, $()));
    for (var i = 0; i < parseInt(evs.count); i++) {
      var e = evs.objectAtIndex(i);
      rows.push({
        t:   ObjC.unwrap(e.title) || '',
        cal: ObjC.unwrap(e.calendar.title),
        s:   ObjC.unwrap(outFmt.stringFromDate(e.startDate)),
        e:   ObjC.unwrap(outFmt.stringFromDate(e.endDate)),
        ad:  e.isAllDay ? 1 : 0,
        st:  parseInt(e.status),
        av:  parseInt(e.availability)
      });
    }
    cur = nxt;
  }
  console.log(JSON.stringify(rows));
}
