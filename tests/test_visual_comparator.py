import pytest
from scripts import benchmark_visual_comparator as b


@pytest.mark.parametrize('ranking', [[1,1], [1], [1,3], ['1',2], [True,2]])
def test_invalid_ranking_cannot_count_as_a_prediction(ranking):
    with pytest.raises(ValueError):
        b.validate_answer({'ranking':ranking},2)


def test_consensus_uses_photo_identity_not_presentation_position():
    assert b.consensus([98,4,61],[4,61,98])==[4,98,61]


def test_large_group_compares_every_photo_in_bounded_calls(monkeypatch,tmp_path):
    monkeypatch.setattr(b,'OUT',tmp_path)
    calls=[]
    def fake(scene,indices,stage,data,protocol):
        calls.append(indices)
        return {'valid':True,'ranking':sorted(indices,reverse=True),'seconds':1.,'answer':{}}
    monkeypatch.setattr(b,'request',fake)
    result=b.rank_group(80,list(range(44)),'forward',{}, {})
    assert all(2<=len(c)<=8 for c in calls)
    assert set().union(*map(set,calls))==set(range(44))
    assert sorted(result['ranking'])==list(range(44))
    assert result['ranking'][0]==43


def test_failed_batch_is_not_silently_replaced_with_baseline(monkeypatch,tmp_path):
    monkeypatch.setattr(b,'OUT',tmp_path)
    monkeypatch.setattr(b,'request',lambda *a: {'valid':False,'ranking':[],'seconds':1.})
    result=b.rank_group(80,list(range(12)),'forward',{}, {})
    assert not result['valid'] and result['ranking']==[]
