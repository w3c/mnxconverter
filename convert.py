from mnxconverter.musicxml import get_score as get_score_from_musicxml
from mnxconverter.mnx_common import put_score as put_mnx_common_score
import sys

if __name__ == "__main__":
    filedata = open(sys.argv[1], 'rb').read()
    s = get_score_from_musicxml(filedata)
    print(put_mnx_common_score(s).decode('utf8'))
