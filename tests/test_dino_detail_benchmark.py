"""Check crop selection without loading model weights or real photographs."""
from scripts.benchmark_dino_detail import detail_boxes, square_box


def test_square_crops_stay_inside_portrait_and_landscape():
    for width,height in [(4000,6000),(6000,4000),(1,1)]:
        for box in [(0,0,.1,.2),(.9,.9,.3,.4),(-.1,-.1,.2,.2),(0,0,1,1)]:
            a,b,c,d=square_box(box,width,height,2)
            assert 0<=a<c<=width and 0<=b<d<=height
            assert c-a==d-b


def test_faces_take_priority_and_have_distinct_views():
    detail={'faces':[{'box':[.1,.1,.1,.1]},{'box':[.7,.2,.1,.1]}], 'people':[[0,0,1,1,.9]]}
    views=detail_boxes(detail,6000,4000)
    assert [kind for _,kind in views]==['face','second_face']
    assert views[0][0]!=views[1][0]


def test_no_face_uses_person_head_region_and_person():
    detail={'faces':[], 'people':[[.25,.1,.4,.8,.9]]}
    views=detail_boxes(detail,4000,6000)
    assert [kind for _,kind in views]==['upper_person','person']
    assert views[0][0][1]<views[1][0][1]


def test_no_detections_uses_explicit_fallback_without_labels():
    detail={'faces':[], 'people':[]}
    views=detail_boxes(detail,6000,4000)
    assert [kind for _,kind in views]==['center_fallback','full_fallback']
    assert views[1][0]==(0,0,6000,4000)
