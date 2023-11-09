from mnxconverter.musicxml import NotationDataError, NotationImportError, get_score as get_score_from_musicxml
from mnxconverter.mnx import put_score as put_mnx_score
import sys

if __name__ == "__main__":
    filedata = open(sys.argv[1], 'rb').read()
    try:
        s = get_score_from_musicxml(filedata)
    except (NotationDataError, NotationImportError) as e:
        print(f'Error: {e.args[0]}')
    else:
        print(put_mnx_score(s).decode('utf8'))
