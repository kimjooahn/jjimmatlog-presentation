(function(global){
  const DEFAULT_REVIEW_SCORE=2.8;
  const PRIOR_REVIEW_COUNT=40;
  function clamp(value,min,max){return Math.min(max,Math.max(min,value))}
  function normalizedText(text){return String(text||'').toLowerCase().replace(/[^가-힣a-z0-9\s]/g,'').replace(/\s+/g,' ').trim()}
  function wordSet(text){return new Set(normalizedText(text).split(' ').filter(Boolean))}
  function similarity(left,right){
    const a=wordSet(left),b=wordSet(right);
    if(!a.size||!b.size)return 0;
    const intersection=[...a].filter(word=>b.has(word)).length;
    return intersection/Math.max(a.size,b.size);
  }
  function calculateReviewReliability(review,reviews){
    const text=String(review.text||'').trim();
    let score=70;
    if(review.hasImage===true)score+=10;
    if(text.length>=20)score+=5;
    if(Number(review.authorReviewCount)>0)score+=Math.min(5,Number(review.authorReviewCount)/20);
    if(text.length<=8)score-=15;
    if(/^(맛있어요|좋아요|최고|굿|추천이에요|괜찮아요)[!.\s]*$/i.test(text))score-=10;
    const others=reviews.filter(item=>item!==review);
    const hasExact=others.some(item=>normalizedText(item.text)===normalizedText(text)&&text.length>0);
    const hasSimilar=others.some(item=>similarity(item.text,text)>=0.75);
    if(hasExact)score-=30;
    else if(hasSimilar)score-=20;
    return Math.round(clamp(score,0,100));
  }
  function limitedReviews(reviews){return Array.isArray(reviews)?reviews.slice(0,100):[]}
  function calculateOriginalScore(reviews){
    const items=limitedReviews(reviews);
    if(!items.length)return 0;
    return Number((items.reduce((sum,item)=>sum+clamp(Number(item.rating)||0,1,5),0)/items.length).toFixed(2));
  }
  function calculateWeightedScore(reviews){
    const items=limitedReviews(reviews);
    if(!items.length)return 0;
    let weightedTotal=0,totalWeight=0;
    items.forEach(review=>{const reliabilityScore=calculateReviewReliability(review,items);const weight=reliabilityScore/100;weightedTotal+=clamp(Number(review.rating)||0,1,5)*weight;totalWeight+=weight});
    return Number((totalWeight?weightedTotal/totalWeight:0).toFixed(2));
  }
  function calculateReviewResults(reviews){
    const items=limitedReviews(reviews);
    const originalScore=calculateOriginalScore(items);
    const reviewReliability=items.map(review=>({id:review.id,reliabilityScore:calculateReviewReliability(review,items),weight:Number((calculateReviewReliability(review,items)/100).toFixed(2))}));
    const weightedScore=calculateWeightedScore(items);
    const averageReliability=reviewReliability.length?Math.round(reviewReliability.reduce((sum,item)=>sum+item.reliabilityScore,0)/reviewReliability.length):0;
    const count=items.length;
    const adjustedScore=Number(((count/(count+PRIOR_REVIEW_COUNT))*weightedScore+(PRIOR_REVIEW_COUNT/(count+PRIOR_REVIEW_COUNT))*DEFAULT_REVIEW_SCORE).toFixed(2));
    const finalScore=Number(clamp(adjustedScore,2.5,4.5).toFixed(2));
    return {reviewCount:count,originalScore,averageReliability,weightedScore,adjustedScore,finalScore,reviewReliability};
  }
  function calculateAdjustedScore(weightedScore,reviewCount){return Number(((reviewCount/(reviewCount+PRIOR_REVIEW_COUNT))*weightedScore+(PRIOR_REVIEW_COUNT/(reviewCount+PRIOR_REVIEW_COUNT))*DEFAULT_REVIEW_SCORE).toFixed(2))}
  function calculateFinalScore(adjustedScore){return Number(clamp(adjustedScore,2.5,4.5).toFixed(2))}
  function runReviewScoreTests(){
    const make=(count,rating,text,extra={})=>Array.from({length:count},(_,index)=>({id:index+1,rating,text:`${text} ${index}`,date:'2026-09-15',...extra}));
    const cases={
      case1:make(3,5,'구체적인 테스트 리뷰입니다',{}),
      case2:make(100,4.5,'음식과 서비스에 대한 구체적인 테스트 리뷰입니다', {hasImage:true,authorReviewCount:35}),
      case3:make(100,3,'가격과 맛을 비교한 테스트 리뷰입니다',{}),
      case4:Array.from({length:100},(_,index)=>({id:index+1,rating:index<85?5:3,text:'맛있어요',date:'2026-09-15',hasImage:false,authorReviewCount:0})),
      case5:make(100,5,'재료의 식감과 직원 응대가 인상적인 구체적인 테스트 리뷰입니다',{hasImage:true,authorReviewCount:60}),
      case6:[...make(90,4,'좋았던 점과 아쉬운 점을 함께 적은 테스트 리뷰입니다'),...make(10,1,'재방문 여부를 고민하게 된 테스트 리뷰입니다')]
    };
    const results={};Object.keys(cases).forEach(key=>{results[key]=calculateReviewResults(cases[key]);});
    console.groupCollapsed('[찐맛로그] 리뷰 점수 알고리즘 테스트');console.table(Object.entries(results).map(([name,result])=>({case:name,reviews:result.reviewCount,original:result.originalScore,reliability:result.averageReliability,weighted:result.weightedScore,adjusted:result.adjustedScore,final:result.finalScore})));console.groupEnd();return results;
  }
  global.ReviewScore={calculateOriginalScore,calculateReviewReliability,calculateWeightedScore,calculateAdjustedScore,calculateFinalScore,calculateReviewResults,runReviewScoreTests};
})(window);
