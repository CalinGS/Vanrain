#!/bin/bash
# usage: scan.sh owner/repo branch
r=$1; b=$2; d=$(echo $r|tr / _)
[ -d $d ] || { git init -q $d; git -C $d remote add origin https://github.com/$r.git; }
git -C $d fetch -q --shallow-since=2026-06-20 origin $b 2>/dev/null
git -C $d log FETCH_HEAD --since=2026-07-01 --no-merges --format='%H|%cs|%s' | while IFS='|' read h dt s; do
  files=$(git -C $d show --format= --name-only $h)
  src=$(echo "$files" | grep '\.py$' | grep -viE '(^|/)(tests?|testing)/|test_|conftest|docs/' | wc -l)
  tst=$(echo "$files" | grep -iE '(^|/)(tests?|testing)/|test_' | wc -l)
  [ "$src" = 1 ] && [ "$tst" -ge 1 ] && echo "$r|$h|$dt|$s"
done
