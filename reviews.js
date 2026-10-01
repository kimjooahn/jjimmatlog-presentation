(function(global){
  function createReviews(seed,baseRating,profile){
    const texts={
      detailed:['음식의 간과 식감이 잘 맞았고 직원 응대도 차분했습니다.','대표 메뉴의 양과 가격을 함께 비교해볼 수 있었던 식사였습니다.','재료의 상태와 주문 후 대기 시간이 만족스러웠던 방문이었습니다.','공간은 조용했고 메뉴 설명이 자세해서 선택하기 편했습니다.','처음 방문했지만 음식과 서비스의 장단점을 모두 확인할 수 있었습니다.'],
      mixed:['맛과 가격을 함께 살펴본 테스트 리뷰입니다.','메뉴 구성이 무난했고 방문 조건을 기록한 테스트 리뷰입니다.','음식의 특징과 서비스 경험을 정리한 테스트 리뷰입니다.'],
      short:['맛있어요','좋아요','최고']
    };
    return Array.from({length:profile.count},(_,index)=>({
      id:`${seed}-${index+1}`,
      rating:Array.isArray(baseRating)?baseRating[index%baseRating.length]:baseRating,
      text:`${texts[profile.type][index%texts[profile.type].length]} (${index+1})`,
      date:`2026-09-${String((index%28)+1).padStart(2,'0')}`,
      hasImage:profile.images?index%3!==1:false,
      authorReviewCount:profile.authorBase?profile.authorBase+(index%6)*4:0
    }));
  }
  global.TEST_REVIEW_DATA={
    'igogip-mandu':createReviews('igogip',4.3,{count:42,type:'detailed',images:true,authorBase:18}),
    'chungnamjip-sundae':createReviews('chungnam',4.5,{count:58,type:'detailed',images:true,authorBase:24}),
    'gobawu-tofu':createReviews('gobawu',4.2,{count:36,type:'mixed',images:false,authorBase:8}),
    'dalsikdang':createReviews('dalsik',4.1,{count:24,type:'mixed',images:false,authorBase:5}),
    'gwangmyeong-mandu':createReviews('gwangmyeong',4.0,{count:18,type:'short',images:false,authorBase:2})
  };
})(window);
