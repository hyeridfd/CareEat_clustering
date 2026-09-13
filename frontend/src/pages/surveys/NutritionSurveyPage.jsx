import { useState, useEffect, useRef } from 'react'
import { useNavigate } from 'react-router-dom'
import api from '../../lib/api'
import SurveyLayout from '../../components/layout/SurveyLayout'
import { InfoBox, Divider } from '../../components/FormFields'

const TOTAL_PAGES = 3
const DAYS = [1, 2, 3, 4, 5]

// ── 5일치 메뉴 데이터 ──
// food: 음식 구분, menu: 메뉴명 (실제 식단에 맞게 수정)
// ── 간식 배식량 기본값 (일차별 공통) ──
const SNACK_DEFAULT_PORTIONS = {
  1: { '간식1': { '간식': 190 }, '간식2': { '간식': 150 } },
  2: { '간식1': { '간식': 125 }, '간식2': { '간식A': 23, '간식B': 190 } },
  3: { '간식1': { '간식': 80  }, '간식2': { '간식A': 23.8, '간식B': 65 } },
  4: { '간식1': { '간식': 190 }, '간식2': { '간식': 118 } },
  5: { '간식1': { '간식': 125 }, '간식2': { '간식': 124.9 } },
}

const MEAL_FOODS_BY_DAY = {
  1: { // 8/7
    '아침': [
      { food: '밥/죽',  menu: '흰밥/흰죽' },
      { food: '국/탕',  menu: '단호박크림스프' },
      { food: '주찬',   menu: '돈채가지볶음' },
      { food: '부찬1',  menu: '건시래기지짐' },
      { food: '부찬2',  menu: '멸치견과류볶음' },
      { food: '김치1',  menu: '배추김치' },
      { food: '김치2',  menu: '백김치' },
    ],
    '간식1': [{ food: '간식', menu: '검은콩두유' }],
    '점심': [
      { food: '밥/죽',  menu: '잡곡밥/영양죽' },
      { food: '국/탕',  menu: '시금치국' },
      { food: '주찬',   menu: '카레라이스' },
      { food: '부찬1',  menu: '돈육육전' },
      { food: '부찬2',  menu: '치커리겉절이' },
      { food: '김치1',  menu: '배추김치' },
      { food: '김치2',  menu: '백김치' },
    ],
    '간식2': [{ food: '간식', menu: '수박' }],
    '저녁': [
      { food: '밥/죽',  menu: '잡곡밥/영양죽' },
      { food: '국/탕',  menu: '김치콩나물국' },
      { food: '주찬',   menu: '가자미허브구이' },
      { food: '부찬1',  menu: '미니새송이버터조림' },
      { food: '부찬2',  menu: '무채초절이' },
      { food: '김치1',  menu: '배추김치' },
      { food: '김치2',  menu: '백김치' },
    ],
  },
  2: { // 8/8
    '아침': [
      { food: '밥/죽',  menu: '흰밥/흰죽' },
      { food: '국/탕',  menu: '숭늉' },
      { food: '주찬',   menu: '우민찌곤약조림' },
      { food: '부찬1',  menu: '숙주나물' },
      { food: '부찬2',  menu: '깻잎찜' },
      { food: '김치1',  menu: '배추김치' },
      { food: '김치2',  menu: '백김치' },
    ],
    '간식1': [{ food: '간식', menu: '비피더스' }],
    '점심': [
      { food: '밥/죽',  menu: '잡곡밥/영양죽' },
      { food: '국/탕',  menu: '냉이된장국' },
      { food: '주찬',   menu: '돈육김치찜' },
      { food: '부찬1',  menu: '건새우그린빈볶음' },
      { food: '부찬2',  menu: '오이상추무침' },
      { food: '김치1',  menu: '배추김치' },
      { food: '김치2',  menu: '백김치' },
    ],
    '간식2': [
      { food: '간식A', menu: '카스타드' },
      { food: '간식B', menu: '주스(델몬트드링크포도)' },
    ],
    '저녁': [
      { food: '밥/죽',  menu: '잡곡밥/영양죽' },
      { food: '국/탕',  menu: '감자양파국' },
      { food: '주찬',   menu: '스크램블에그' },
      { food: '부찬1',  menu: '마파두부조림' },
      { food: '부찬2',  menu: '꼬시래기무무무침' },
      { food: '김치1',  menu: '배추김치' },
      { food: '김치2',  menu: '백김치' },
    ],
  },
  3: { // 8/27
    '아침': [
      { food: '밥/죽',  menu: '흰밥/잡곡죽' },
      { food: '국/탕',  menu: '유채국' },
      { food: '주찬',   menu: '참치무조림' },
      { food: '부찬1',  menu: '느타리버섯볶음' },
      { food: '부찬2',  menu: '오이지무침' },
      { food: '김치1',  menu: '배추김치' },
      { food: '김치2',  menu: '백김치' },
    ],
    '간식1': [{ food: '간식', menu: '떠먹는요거트' }],
    '점심':  [
      { food: '밥/죽',  menu: '잡곡밥/영양죽(유채죽)' },
      { food: '국/탕',  menu: '잔치국수' },
      { food: '주찬',   menu: '새우튀김샐러드' },
      { food: '부찬1',  menu: '후랑크마늘쫑볶음' },
      { food: '부찬2',  menu: '표고버섯볶음' },
      { food: '김치1',  menu: '배추김치' },
      { food: '김치2',  menu: '백김치' },
    ],
    '간식2': [
      { food: '간식A', menu: '마가렛트' },
      { food: '간식B', menu: '요구르트' },
    ],
    '저녁':  [
      { food: '밥/죽',  menu: '잡곡밥/영양죽(표고죽)' },
      { food: '국/탕',  menu: '콩나물국' },
      { food: '주찬',   menu: '훈제오리*단호박찜' },
      { food: '부찬1',  menu: '쌈무' },
      { food: '부찬2',  menu: '열무겉절이' },
      { food: '김치1',  menu: '배추김치' },
      { food: '김치2',  menu: '백김치' },
    ],
  },
  4: { // 8/28
    '아침': [
      { food: '밥/죽',  menu: '흰밥/잡곡죽 (HS09: 흰죽)' },
      { food: '국/탕',  menu: '민물새우맑은탕' },
      { food: '주찬',   menu: '두부양념조림' },
      { food: '부찬1',  menu: '치커리겉절이' },
      { food: '부찬2',  menu: '콩나물무침' },
      { food: '김치1',  menu: '배추김치' },
      { food: '김치2',  menu: '백김치' },
    ],
    '간식1': [{ food: '간식', menu: '검은콩두유' }],
    '점심':  [
      { food: '밥/죽',  menu: '잡곡밥/영양죽(콩나물죽) (HS09: 흰죽)' },
      { food: '국/탕',  menu: '고추장찌개' },
      { food: '주찬',   menu: '바베큐찜닭' },
      { food: '부찬1',  menu: '연근검은깨강정' },
      { food: '부찬2',  menu: '배추된장나물' },
      { food: '김치1',  menu: '배추김치' },
      { food: '김치2',  menu: '백김치' },
    ],
    '간식2': [{ food: '간식', menu: '푸딩' }], // 실제 메뉴는 elderlyId 기반으로 동적 결정
    '저녁':  [
      { food: '밥/죽',  menu: '잡곡밥/영양죽(닭+배추죽) (HS09: 흰죽)' },
      { food: '국/탕',  menu: '시금치국' },
      { food: '주찬',   menu: '삼치무조림' },
      { food: '부찬1',  menu: '건고구마순볶음' },
      { food: '부찬2',  menu: '비트모듬피클' },
      { food: '김치1',  menu: '배추김치' },
      { food: '김치2',  menu: '백김치' },
    ],
  },
  5: { // 8/29
    '아침': [
      { food: '밥/죽',  menu: '흰밥/잡곡죽 (HS09,HS29: 흰죽)' },
      { food: '국/탕',  menu: '토란국' },
      { food: '주찬',   menu: '돈민찌표고곤약조림' },
      { food: '부찬1',  menu: '얼갈이나물' },
      { food: '부찬2',  menu: '갓절임무침' },
      { food: '김치1',  menu: '배추김치' },
      { food: '김치2',  menu: '백김치' },
    ],
    '간식1': [{ food: '간식', menu: '비피더스' }],
    '점심':  [
      { food: '밥/죽',  menu: '잡곡밥/영양죽(두부죽) (HS09: 흰죽)' },
      { food: '국/탕',  menu: '배추국' },
      { food: '주찬',   menu: '고등어양념구이' },
      { food: '부찬1',  menu: '통들깨무나물' },
      { food: '부찬2',  menu: '목이오리엔탈무침' },
      { food: '김치1',  menu: '배추김치' },
      { food: '김치2',  menu: '백김치' },
    ],
    '간식2': [{ food: '간식', menu: '바나나' }],
    '저녁':  [
      { food: '밥/죽',  menu: '잡곡밥/영양죽(목이버섯죽) (HS09: 흰죽)' },
      { food: '국/탕',  menu: '콩가루두부아욱국' },
      { food: '주찬',   menu: '스크램블에그' },
      { food: '부찬1',  menu: '비엔나피망조림' },
      { food: '부찬2',  menu: '미역초무침' },
      { food: '김치1',  menu: '배추김치' },
      { food: '김치2',  menu: '백김치' },
    ],
  },
}


const MEALS = ['아침', '간식1', '점심', '간식2', '저녁']

// ── 배식량 기본값 (meal_form별, 1~2일차) ──
const DEFAULT_PORTIONS = {
  1: {
    '아침': {
      "죽/일반찬": { "밥/죽": 235.8, "국/탕": 118.5, "주찬": 82.7, "부찬1": 31.3, "부찬2": 10.9, "김치1": 38.3 },
      "일반밥/다진찬": { "밥/죽": 151.0, "국/탕": 118.5, "주찬": 55.8, "부찬1": 35.4, "부찬2": 12.2, "김치1": 30.2 },
      "일반밥/일반찬": { "밥/죽": 151.0, "국/탕": 118.5, "주찬": 82.7, "부찬1": 31.3, "부찬2": 10.9, "김치1": 38.3 },
      "죽/다진찬": { "밥/죽": 235.8, "국/탕": 118.5, "주찬": 55.8, "부찬1": 35.4, "부찬2": 12.2, "김치1": 30.2 },
      "갈죽/갈찬": { "밥/죽": 183.8, "국/탕": 118.5, "주찬": 76.8, "부찬1": 27.3, "부찬2": 24.0, "김치2": 35.3 },
      "죽/갈찬": { "밥/죽": 235.8, "국/탕": 118.5, "주찬": 76.8, "부찬1": 27.3, "부찬2": 24.0, "김치2": 35.3 },
      "일반밥/일반찬(백김치)": { "밥/죽": 151.0, "국/탕": 118.5, "주찬": 82.7, "부찬1": 31.3, "부찬2": 10.9, "김치2": 71.5 },
      "일반밥/다진찬(다진백김치)": { "밥/죽": 151.0, "국/탕": 118.5, "주찬": 55.8, "부찬1": 35.4, "부찬2": 12.2, "김치2": 50.5 },
      "죽/갈찬(다진백김치)": { "밥/죽": 235.8, "국/탕": 118.5, "주찬": 76.8, "부찬1": 27.3, "부찬2": 24.0, "김치2": 50.5 },
    },
    '점심': {
      "죽/일반찬": { "밥/죽": 303.3, "국/탕": 183.2, "주찬": 204.9, "부찬1": 38.1, "부찬2": 26.5, "김치1": 31.5 },
      "일반밥/다진찬": { "밥/죽": 180.0, "국/탕": 183.2, "주찬": 204.9, "부찬1": 29.0, "부찬2": 31.0, "김치1": 39.1 },
      "일반밥/일반찬": { "밥/죽": 180.0, "국/탕": 183.2, "주찬": 204.9, "부찬1": 38.1, "부찬2": 26.5, "김치1": 31.5 },
      "죽/다진찬": { "밥/죽": 303.3, "국/탕": 183.2, "주찬": 204.9, "부찬1": 29.0, "부찬2": 31.0, "김치1": 39.1 },
      "갈죽/갈찬": { "밥/죽": 183.0, "국/탕": 113.2, "주찬": 70.0, "부찬1": 35.1, "부찬2": 28.8, "김치2": 38.6 },
      "죽/갈찬": { "밥/죽": 303.3, "국/탕": 113.2, "주찬": 70.0, "부찬1": 35.1, "부찬2": 28.8, "김치2": 38.6 },
      "일반밥/일반찬(백김치)": { "밥/죽": 180.0, "국/탕": 183.2, "주찬": 204.9, "부찬1": 38.1, "부찬2": 26.5, "김치2": 44.4 },
      "일반밥/다진찬(다진백김치)": { "밥/죽": 180.0, "국/탕": 183.2, "주찬": 204.9, "부찬1": 29.0, "부찬2": 31.0, "김치2": 33.2 },
      "죽/갈찬(다진백김치)": { "밥/죽": 303.3, "국/탕": 113.2, "주찬": 70.0, "부찬1": 35.1, "부찬2": 28.8, "김치2": 33.2 },
    },
    '저녁': {
      "죽/일반찬": { "밥/죽": 317.2, "국/탕": 198.2, "주찬": 54.8, "부찬1": 58.5, "부찬2": 39.7, "김치1": 31.2 },
      "일반밥/다진찬": { "밥/죽": 132.6, "국/탕": 198.2, "주찬": 54.8, "부찬1": 39.9, "부찬2": 37.0, "김치1": 39.5 },
      "일반밥/일반찬": { "밥/죽": 132.6, "국/탕": 198.2, "주찬": 54.8, "부찬1": 58.5, "부찬2": 39.7, "김치1": 31.2 },
      "죽/다진찬": { "밥/죽": 317.2, "국/탕": 198.2, "주찬": 54.8, "부찬1": 39.9, "부찬2": 37.0, "김치1": 39.5 },
      "갈죽/갈찬": { "밥/죽": 324.2, "국/탕": 154.1, "주찬": 117.0, "부찬1": 40.1, "부찬2": 33.4, "김치2": 40.4 },
      "죽/갈찬": { "밥/죽": 317.2, "국/탕": 154.1, "주찬": 117.0, "부찬1": 40.1, "부찬2": 33.4, "김치2": 40.4 },
      "일반밥/일반찬(백김치)": { "밥/죽": 132.6, "국/탕": 198.2, "주찬": 54.8, "부찬1": 58.5, "부찬2": 39.7, "김치2": 61.2 },
      "일반밥/다진찬(다진백김치)": { "밥/죽": 132.6, "국/탕": 198.2, "주찬": 54.8, "부찬1": 39.9, "부찬2": 37.0, "김치2": 31.5 },
      "죽/갈찬(다진백김치)": { "밥/죽": 317.2, "국/탕": 154.1, "주찬": 117.0, "부찬1": 40.1, "부찬2": 33.4, "김치2": 31.5 },
    },
  },
  2: {
    '아침': {
      "죽/일반찬": { "밥/죽": 273.4, "국/탕": 233.5, "주찬": 77.3, "부찬1": 29.8, "부찬2": 30.1, "김치1": 45.0 },
      "일반밥/다진찬": { "밥/죽": 169.5, "국/탕": 233.5, "주찬": 65.0, "부찬1": 33.4, "부찬2": 19.1, "김치1": 43.1 },
      "일반밥/일반찬": { "밥/죽": 169.5, "국/탕": 233.5, "주찬": 77.3, "부찬1": 29.8, "부찬2": 30.1, "김치1": 45.0 },
      "죽/다진찬": { "밥/죽": 273.4, "국/탕": 233.5, "주찬": 65.0, "부찬1": 33.4, "부찬2": 19.1, "김치1": 43.1 },
      "갈죽/갈찬": { "밥/죽": 236.5, "국/탕": 98.6, "주찬": 76.6, "부찬1": 27.0, "부찬2": 32.9, "김치2": 42.7 },
      "죽/갈찬": { "밥/죽": 273.4, "국/탕": 98.6, "주찬": 76.6, "부찬1": 27.0, "부찬2": 32.9, "김치2": 42.7 },
      "일반밥/일반찬(백김치)": { "밥/죽": 169.5, "국/탕": 233.5, "주찬": 77.3, "부찬1": 29.8, "부찬2": 30.1, "김치2": 71.5 },
      "일반밥/다진찬(다진백김치)": { "밥/죽": 169.5, "국/탕": 233.5, "주찬": 65.0, "부찬1": 33.4, "부찬2": 19.1, "김치2": 50.5 },
      "죽/갈찬(다진백김치)": { "밥/죽": 273.4, "국/탕": 98.6, "주찬": 76.6, "부찬1": 27.0, "부찬2": 32.9, "김치2": 50.5 },
    },
    '점심': {
      "죽/일반찬": { "밥/죽": 308.4, "국/탕": 183.2, "주찬": 75.7, "부찬1": 35.2, "부찬2": 38.5, "김치1": 31.5 },
      "일반밥/다진찬": { "밥/죽": 187.1, "국/탕": 183.2, "주찬": 66.0, "부찬1": 23.8, "부찬2": 57.5, "김치1": 39.1 },
      "일반밥/일반찬": { "밥/죽": 187.1, "국/탕": 183.2, "주찬": 75.7, "부찬1": 35.2, "부찬2": 38.5, "김치1": 31.5 },
      "죽/다진찬": { "밥/죽": 308.4, "국/탕": 183.2, "주찬": 66.0, "부찬1": 23.8, "부찬2": 57.5, "김치1": 39.1 },
      "갈죽/갈찬": { "밥/죽": 243.3, "국/탕": 113.2, "주찬": 39.2, "부찬1": 47.4, "부찬2": 37.5, "김치2": 35.7 },
      "죽/갈찬": { "밥/죽": 308.4, "국/탕": 113.2, "주찬": 39.2, "부찬1": 47.4, "부찬2": 37.5, "김치2": 35.7 },
      "일반밥/일반찬(백김치)": { "밥/죽": 187.1, "국/탕": 183.2, "주찬": 75.7, "부찬1": 35.2, "부찬2": 38.5, "김치2": 46.4 },
      "일반밥/다진찬(다진백김치)": { "밥/죽": 187.1, "국/탕": 183.2, "주찬": 66.0, "부찬1": 23.8, "부찬2": 57.5, "김치2": 40.8 },
      "죽/갈찬(다진백김치)": { "밥/죽": 308.4, "국/탕": 113.2, "주찬": 39.2, "부찬1": 47.4, "부찬2": 37.5, "김치2": 40.8 },
    },
    '저녁': {
      "죽/일반찬": { "밥/죽": 228.7, "국/탕": 175.9, "주찬": 56.3, "부찬1": 99.7, "부찬2": 41.5, "김치1": 32.3 },
      "일반밥/다진찬": { "밥/죽": 192.7, "국/탕": 175.9, "주찬": 39.2, "부찬1": 56.0, "부찬2": 29.5, "김치1": 59.3 },
      "일반밥/일반찬": { "밥/죽": 192.7, "국/탕": 175.9, "주찬": 56.3, "부찬1": 99.7, "부찬2": 41.5, "김치1": 32.3 },
      "죽/다진찬": { "밥/죽": 228.7, "국/탕": 175.9, "주찬": 39.2, "부찬1": 56.0, "부찬2": 29.5, "김치1": 59.3 },
      "갈죽/갈찬": { "밥/죽": 156.3, "국/탕": 107.0, "주찬": 68.0, "부찬1": 54.9, "부찬2": 45.0, "김치2": 49.1 },
      "죽/갈찬": { "밥/죽": 228.7, "국/탕": 107.0, "주찬": 68.0, "부찬1": 54.9, "부찬2": 45.0, "김치2": 49.1 },
      "일반밥/일반찬(백김치)": { "밥/죽": 192.7, "국/탕": 175.9, "주찬": 56.3, "부찬1": 99.7, "부찬2": 41.5, "김치2": 65.7 },
      "일반밥/다진찬(다진백김치)": { "밥/죽": 192.7, "국/탕": 175.9, "주찬": 39.2, "부찬1": 56.0, "부찬2": 29.5, "김치2": 56.8 },
      "죽/갈찬(다진백김치)": { "밥/죽": 228.7, "국/탕": 107.0, "주찬": 68.0, "부찬1": 54.9, "부찬2": 45.0, "김치2": 56.8 },
    },
  },
  3: {
    '아침': {
      "죽/일반찬": { "밥/죽": 236.0, "국/탕": 226.2, "주찬": 102.1, "부찬1": 47.6, "부찬2": 37.7, "김치1": 68.1 },
      "일반밥/다진찬": { "밥/죽": 151.8, "국/탕": 226.2, "주찬": 51.4, "부찬1": 48.0, "부찬2": 29.5, "김치1": 47.9 },
      "일반밥/일반찬": { "밥/죽": 151.8, "국/탕": 226.2, "주찬": 102.1, "부찬1": 47.6, "부찬2": 37.7, "김치1": 68.1 },
      "죽/다진찬": { "밥/죽": 236.0, "국/탕": 226.2, "주찬": 51.4, "부찬1": 48.0, "부찬2": 29.5, "김치1": 47.9 },
      "갈죽/갈찬": { "밥/죽": 241.5, "국/탕": 79.2, "주찬": 50.7, "부찬1": 18.8, "부찬2": 26.5, "김치2": 42.3 },
      "죽/갈찬": { "밥/죽": 236.0, "국/탕": 79.2, "주찬": 50.7, "부찬1": 18.8, "부찬2": 26.5, "김치2": 42.3 },
      "일반밥/일반찬(백김치)": { "밥/죽": 151.8, "국/탕": 226.2, "주찬": 102.1, "부찬1": 47.6, "부찬2": 37.7, "김치2": 62.6 },
      "일반밥/다진찬(다진백김치)": { "밥/죽": 151.8, "국/탕": 226.2, "주찬": 51.4, "부찬1": 48.0, "부찬2": 29.5, "김치2": 54.9 },
      "죽/갈찬(다진백김치)": { "밥/죽": 236.0, "국/탕": 79.2, "주찬": 50.7, "부찬1": 18.8, "부찬2": 26.5, "김치2": 54.9 },
    },
    '점심': {
      "죽/일반찬": { "밥/죽": 230.0, "국/탕": 83.3, "주찬": 55.2, "부찬1": 42.1, "부찬2": 62.0, "김치1": 58.8 },
      "일반밥/다진찬": { "밥/죽": 110.3, "국/탕": 183.0, "주찬": 46.4, "부찬1": 41.1, "부찬2": 56.0, "김치1": 49.1 },
      "일반밥/일반찬": { "밥/죽": 110.3, "국/탕": 183.0, "주찬": 55.2, "부찬1": 42.1, "부찬2": 62.0, "김치1": 58.8 },
      "죽/다진찬": { "밥/죽": 230.0, "국/탕": 83.3, "주찬": 46.4, "부찬1": 41.1, "부찬2": 56.0, "김치1": 49.1 },
      "갈죽/갈찬": { "밥/죽": 192.4, "국/탕": 88.4, "주찬": 50.9, "부찬1": 44.9, "부찬2": 41.2, "김치2": 37.5 },
      "죽/갈찬": { "밥/죽": 230.0, "국/탕": 88.4, "주찬": 50.9, "부찬1": 44.9, "부찬2": 41.2, "김치2": 37.5 },
      "일반밥/일반찬(백김치)": { "밥/죽": 110.3, "국/탕": 183.0, "주찬": 55.2, "부찬1": 42.1, "부찬2": 62.0, "김치2": 52.6 },
      "일반밥/다진찬(다진백김치)": { "밥/죽": 110.3, "국/탕": 183.0, "주찬": 46.4, "부찬1": 41.1, "부찬2": 56.0, "김치2": 51.2 },
      "죽/갈찬(다진백김치)": { "밥/죽": 230.0, "국/탕": 88.4, "주찬": 50.9, "부찬1": 44.9, "부찬2": 41.2, "김치2": 51.2 },
    },
    '저녁': {
      "죽/일반찬": { "밥/죽": 305.8, "국/탕": 223.7, "주찬": 74.3, "부찬1": 44.3, "부찬2": 43.2, "김치1": 59.6 },
      "일반밥/다진찬": { "밥/죽": 155.5, "국/탕": 223.7, "주찬": 65.6, "부찬1": 47.9, "부찬2": 40.3, "김치1": 44.7 },
      "일반밥/일반찬": { "밥/죽": 155.5, "국/탕": 223.7, "주찬": 74.3, "부찬1": 44.3, "부찬2": 43.2, "김치1": 59.6 },
      "죽/다진찬": { "밥/죽": 305.8, "국/탕": 223.7, "주찬": 65.6, "부찬1": 47.9, "부찬2": 40.3, "김치1": 44.7 },
      "갈죽/갈찬": { "밥/죽": 160.5, "국/탕": 91.3, "주찬": 43.9, "부찬1": 27.6, "부찬2": 39.8, "김치2": 37.3 },
      "죽/갈찬": { "밥/죽": 305.8, "국/탕": 91.3, "주찬": 43.9, "부찬1": 27.6, "부찬2": 39.8, "김치2": 37.3 },
      "일반밥/일반찬(백김치)": { "밥/죽": 155.5, "국/탕": 223.7, "주찬": 74.3, "부찬1": 44.3, "부찬2": 43.2, "김치2": 48.7 },
      "일반밥/다진찬(다진백김치)": { "밥/죽": 155.5, "국/탕": 223.7, "주찬": 65.6, "부찬1": 47.9, "부찬2": 40.3, "김치2": 39.6 },
      "죽/갈찬(다진백김치)": { "밥/죽": 305.8, "국/탕": 91.3, "주찬": 43.9, "부찬1": 27.6, "부찬2": 39.8, "김치2": 39.6 },
    },
  },
  4: {
    '아침': {
      "죽/일반찬": { "밥/죽": 218.5, "국/탕": 131.2, "주찬": 81.9, "부찬1": 24.1, "부찬2": 27.9, "김치1": 53.6 },
      "일반밥/다진찬": { "밥/죽": 164.0, "국/탕": 131.2, "주찬": 35.8, "부찬1": 20.4, "부찬2": 24.4, "김치1": 55.5 },
      "일반밥/일반찬": { "밥/죽": 164.0, "국/탕": 131.2, "주찬": 81.9, "부찬1": 24.1, "부찬2": 27.9, "김치1": 53.6 },
      "죽/다진찬": { "밥/죽": 218.5, "국/탕": 131.2, "주찬": 35.8, "부찬1": 20.4, "부찬2": 24.4, "김치1": 55.5 },
      "갈죽/갈찬": { "밥/죽": 105.7, "국/탕": 71.8, "주찬": 40.8, "부찬1": 36.5, "부찬2": 35.9, "김치2": 33.4 },
      "죽/갈찬": { "밥/죽": 218.5, "국/탕": 71.8, "주찬": 40.8, "부찬1": 36.5, "부찬2": 35.9, "김치2": 33.4 },
      "일반밥/일반찬(백김치)": { "밥/죽": 164.0, "국/탕": 131.2, "주찬": 81.9, "부찬1": 24.1, "부찬2": 27.9, "김치2": 65.1 },
      "일반밥/다진찬(다진백김치)": { "밥/죽": 164.0, "국/탕": 131.2, "주찬": 35.8, "부찬1": 20.4, "부찬2": 24.4, "김치2": 45.3 },
      "죽/갈찬(다진백김치)": { "밥/죽": 218.5, "국/탕": 71.8, "주찬": 40.8, "부찬1": 36.5, "부찬2": 35.9, "김치2": 45.3 },
      "일반밥/일반찬_HS09": { "밥/죽": 155.9 },
    },
    '점심': {
      "죽/일반찬": { "밥/죽": 311.7, "국/탕": 131.7, "주찬": 82.9, "부찬1": 34.6, "부찬2": 49.5, "김치1": 60.4 },
      "일반밥/다진찬": { "밥/죽": 147.1, "국/탕": 131.7, "주찬": 54.0, "부찬1": 25.3, "부찬2": 38.4, "김치1": 54.9 },
      "일반밥/일반찬": { "밥/죽": 147.1, "국/탕": 131.7, "주찬": 82.9, "부찬1": 34.6, "부찬2": 49.5, "김치1": 60.4 },
      "죽/다진찬": { "밥/죽": 311.7, "국/탕": 131.7, "주찬": 54.0, "부찬1": 25.3, "부찬2": 38.4, "김치1": 54.9 },
      "갈죽/갈찬": { "밥/죽": 213.2, "국/탕": 152.6, "주찬": 41.5, "부찬1": 42.3, "부찬2": 37.1, "김치2": 33.8 },
      "죽/갈찬": { "밥/죽": 311.7, "국/탕": 152.6, "주찬": 41.5, "부찬1": 42.3, "부찬2": 37.1, "김치2": 33.8 },
      "일반밥/일반찬(백김치)": { "밥/죽": 147.1, "국/탕": 131.7, "주찬": 82.9, "부찬1": 34.6, "부찬2": 49.5, "김치2": 60.6 },
      "일반밥/다진찬(다진백김치)": { "밥/죽": 147.1, "국/탕": 131.7, "주찬": 54.0, "부찬1": 25.3, "부찬2": 38.4, "김치2": 44.2 },
      "죽/갈찬(다진백김치)": { "밥/죽": 311.7, "국/탕": 152.6, "주찬": 41.5, "부찬1": 42.3, "부찬2": 37.1, "김치2": 44.2 },
      "일반밥/일반찬_HS09": { "밥/죽": 310.6 },
    },
    '저녁': {
      "죽/일반찬": { "밥/죽": 302.3, "국/탕": 135.4, "주찬": 114.4, "부찬1": 42.7, "부찬2": 53.9, "김치1": 61.8 },
      "일반밥/다진찬": { "밥/죽": 155.1, "국/탕": 135.4, "주찬": 114.4, "부찬1": 52.0, "부찬2": 40.2, "김치1": 43.7 },
      "일반밥/일반찬": { "밥/죽": 155.1, "국/탕": 135.4, "주찬": 114.4, "부찬1": 42.7, "부찬2": 53.9, "김치1": 61.8 },
      "죽/다진찬": { "밥/죽": 302.3, "국/탕": 135.4, "주찬": 114.4, "부찬1": 52.0, "부찬2": 40.2, "김치1": 43.7 },
      "갈죽/갈찬": { "밥/죽": 254.9, "국/탕": 74.2, "주찬": 45.7, "부찬1": 47.1, "부찬2": 25.6, "김치2": 37.8 },
      "죽/갈찬": { "밥/죽": 302.3, "국/탕": 74.2, "주찬": 45.7, "부찬1": 47.1, "부찬2": 25.6, "김치2": 37.8 },
      "일반밥/일반찬(백김치)": { "밥/죽": 155.1, "국/탕": 135.4, "주찬": 114.4, "부찬1": 42.7, "부찬2": 53.9, "김치2": 72.6 },
      "일반밥/다진찬(다진백김치)": { "밥/죽": 155.1, "국/탕": 135.4, "주찬": 114.4, "부찬1": 52.0, "부찬2": 40.2, "김치2": 44.5 },
      "죽/갈찬(다진백김치)": { "밥/죽": 302.3, "국/탕": 74.2, "주찬": 45.7, "부찬1": 47.1, "부찬2": 25.6, "김치2": 44.5 },
      "일반밥/일반찬_HS09": { "밥/죽": 266.5 },
    },
  },
  5: {
    '아침': {
      "죽/일반찬": { "밥/죽": 296.0, "국/탕": 125.4, "주찬": 64.5, "부찬1": 17.7, "부찬2": 32.4, "김치1": 34.3 },
      "일반밥/다진찬": { "밥/죽": 159.5, "국/탕": 125.4, "주찬": 44.3, "부찬1": 34.3, "부찬2": 42.0, "김치1": 35.3 },
      "일반밥/일반찬": { "밥/죽": 159.5, "국/탕": 125.4, "주찬": 64.5, "부찬1": 17.7, "부찬2": 32.4, "김치1": 34.3 },
      "죽/다진찬": { "밥/죽": 296.0, "국/탕": 125.4, "주찬": 44.3, "부찬1": 34.3, "부찬2": 42.0, "김치1": 35.3 },
      "갈죽/갈찬": { "밥/죽": 217.8, "국/탕": 80.7, "주찬": 39.1, "부찬1": 40.8, "부찬2": 24.0, "김치2": 33.7 },
      "죽/갈찬": { "밥/죽": 296.0, "국/탕": 80.7, "주찬": 39.1, "부찬1": 40.8, "부찬2": 24.0, "김치2": 33.7 },
      "일반밥/일반찬(백김치)": { "밥/죽": 159.5, "국/탕": 125.4, "주찬": 64.5, "부찬1": 17.7, "부찬2": 32.4, "김치2": 33.4 },
      "일반밥/다진찬(다진백김치)": { "밥/죽": 159.5, "국/탕": 125.4, "주찬": 44.3, "부찬1": 34.3, "부찬2": 42.0, "김치2": 26.4 },
      "죽/갈찬(다진백김치)": { "밥/죽": 296.0, "국/탕": 80.7, "주찬": 39.1, "부찬1": 40.8, "부찬2": 24.0, "김치2": 26.4 },
      "일반밥/일반찬_HS09": { "밥/죽": 353.8 },
      "죽/다진찬_HS29": { "밥/죽": 353.8 },
    },
    '점심': {
      "죽/일반찬": { "밥/죽": 320.5, "국/탕": 151.0, "주찬": 35.4, "부찬1": 28.3, "부찬2": 29.6, "김치1": 39.6 },
      "일반밥/다진찬": { "밥/죽": 215.1, "국/탕": 151.0, "주찬": 35.4, "부찬1": 25.6, "부찬2": 31.0, "김치1": 36.2 },
      "일반밥/일반찬": { "밥/죽": 215.1, "국/탕": 151.0, "주찬": 35.4, "부찬1": 28.3, "부찬2": 29.6, "김치1": 39.6 },
      "죽/다진찬": { "밥/죽": 320.5, "국/탕": 151.0, "주찬": 35.4, "부찬1": 25.6, "부찬2": 31.0, "김치1": 36.2 },
      "갈죽/갈찬": { "밥/죽": 285.9, "국/탕": 80.4, "주찬": 75.0, "부찬1": 32.6, "부찬2": 30.8, "김치2": 34.4 },
      "죽/갈찬": { "밥/죽": 320.5, "국/탕": 80.4, "주찬": 75.0, "부찬1": 32.6, "부찬2": 30.8, "김치2": 34.4 },
      "일반밥/일반찬(백김치)": { "밥/죽": 215.1, "국/탕": 151.0, "주찬": 35.4, "부찬1": 28.3, "부찬2": 29.6, "김치2": 35.0 },
      "일반밥/다진찬(다진백김치)": { "밥/죽": 215.1, "국/탕": 151.0, "주찬": 35.4, "부찬1": 25.6, "부찬2": 31.0, "김치2": 37.6 },
      "죽/갈찬(다진백김치)": { "밥/죽": 320.5, "국/탕": 80.4, "주찬": 75.0, "부찬1": 32.6, "부찬2": 30.8, "김치2": 37.6 },
      "일반밥/일반찬_HS09": { "밥/죽": 346.2 },
    },
    '저녁': {
      "죽/일반찬": { "밥/죽": 330.6, "국/탕": 160.8, "주찬": 43.2, "부찬1": 63.0, "부찬2": 26.8, "김치1": 56.6 },
      "일반밥/다진찬": { "밥/죽": 141.0, "국/탕": 160.8, "주찬": 43.2, "부찬1": 35.7, "부찬2": 24.8, "김치1": 37.5 },
      "일반밥/일반찬": { "밥/죽": 141.0, "국/탕": 160.8, "주찬": 43.2, "부찬1": 63.0, "부찬2": 26.8, "김치1": 56.6 },
      "죽/다진찬": { "밥/죽": 330.6, "국/탕": 160.8, "주찬": 43.2, "부찬1": 35.7, "부찬2": 24.8, "김치1": 37.5 },
      "갈죽/갈찬": { "밥/죽": 278.6, "국/탕": 87.3, "주찬": 68.9, "부찬1": 38.5, "부찬2": 39.0, "김치2": 51.8 },
      "죽/갈찬": { "밥/죽": 330.6, "국/탕": 87.3, "주찬": 68.9, "부찬1": 38.5, "부찬2": 39.0, "김치2": 51.8 },
      "일반밥/일반찬(백김치)": { "밥/죽": 141.0, "국/탕": 160.8, "주찬": 43.2, "부찬1": 63.0, "부찬2": 26.8, "김치2": 56.2 },
      "일반밥/다진찬(다진백김치)": { "밥/죽": 141.0, "국/탕": 160.8, "주찬": 43.2, "부찬1": 35.7, "부찬2": 24.8, "김치2": 30.7 },
      "죽/갈찬(다진백김치)": { "밥/죽": 330.6, "국/탕": 87.3, "주찬": 68.9, "부찬1": 38.5, "부찬2": 39.0, "김치2": 30.7 },
      "일반밥/일반찬_HS09": { "밥/죽": 372.4 },
    },
  },
}

const APPLICABLE_MEAL_FORMS = ['죽/일반찬','일반밥/다진찬','일반밥/일반찬','죽/다진찬','갈죽/갈찬','죽/갈찬']

// 괄호 포함 특이 meal_form → DEFAULT_PORTIONS 키로 직접 매핑
const MEAL_FORM_MAP = {
  '일반밥/일반찬(백김치)':     '일반밥/일반찬(백김치)',
  '일반밥/다진찬(다진백김치)': '일반밥/다진찬(다진백김치)',
  '죽/갈찬(다진백김치)':       '죽/갈찬(다진백김치)',
}

const normalizeMealForm = (mf) => MEAL_FORM_MAP[mf] || mf

// 괄호 포함 특이 meal_form → 기본 meal_form으로 매핑


// ── 잔반량 원형 SVG ──
function WasteCircle({ level, size = 40 }) {
  const fills = [
    null,
    'M 50 50 L 50 5 A 45 45 0 0 1 95 50 Z',
    'M 50 50 L 50 5 A 45 45 0 0 1 50 95 Z',
    'M 50 50 L 50 5 A 45 45 0 1 1 5 50 Z',
    null,
  ]
  return (
    <svg viewBox="0 0 100 100" style={{ width: size, height: size, flexShrink: 0 }}>
      <circle cx="50" cy="50" r="45" fill={level === 4 ? '#2c3e50' : 'white'} stroke="#333" strokeWidth="3" />
      {fills[level] && <path d={fills[level]} fill="#2c3e50" />}
    </svg>
  )
}

// ── 그램 입력 ──
function GramInput({ label, menu, value, onChange, isSnack = false }) {
  const val = value ?? 100
  const isDeferred = val === '추후섭취'
  return (
    <div className="flex items-center gap-2 py-2.5 border-b border-gray-100 last:border-0">
      <div className="w-16 shrink-0">
        <span className="text-sm text-gray-700 font-medium block">{label}</span>
        {menu && <span className="text-xs text-blue-500 leading-tight block">{menu}</span>}
      </div>
      {isDeferred ? (
        <div className="flex-1 flex items-center gap-2">
          <span className="flex-1 text-center text-sm font-medium text-orange-600 bg-orange-50 border border-orange-200 rounded-lg py-2">추후 섭취</span>
          <button type="button" onClick={() => onChange(100)} className="text-xs text-gray-500 underline shrink-0">취소</button>
        </div>
      ) : (
        <>
          <input type="number" min={0} step={1} value={val}
            onChange={e => onChange(Number(e.target.value) || 0)}
            className="flex-1 min-w-0 border border-gray-300 rounded-lg px-2 py-2 text-sm text-center font-medium text-gray-800 bg-white focus:outline-none focus:ring-2 focus:ring-blue-400" />
          <span className="text-xs text-gray-400 shrink-0">g</span>
          <button type="button" onClick={() => onChange(Math.max(0, val - 10))}
            className="w-9 h-9 shrink-0 flex items-center justify-center bg-gray-100 hover:bg-gray-200 rounded-lg border border-gray-200 text-gray-600 font-bold text-lg">−</button>
          <button type="button" onClick={() => onChange(val + 10)}
            className="w-9 h-9 shrink-0 flex items-center justify-center bg-blue-100 hover:bg-blue-200 rounded-lg border border-blue-200 text-blue-700 font-bold text-lg">+</button>
        </>
      )}
      {isSnack && !isDeferred && (
        <button type="button" onClick={() => onChange('추후섭취')}
          className="shrink-0 text-xs px-2 py-1.5 rounded-lg border-2 border-orange-300 text-orange-600 bg-orange-50 hover:bg-orange-100 whitespace-nowrap leading-tight">
          추후<br/>섭취
        </button>
      )}
    </div>
  )
}

// ── 잔반 선택 ──
function WasteSelector({ label, menu, value, onChange, isSnack = false }) {
  const levels = [
    { v: 0, l: '다 먹음' }, { v: 1, l: '25%' }, { v: 2, l: '50%' }, { v: 3, l: '75%' }, { v: 4, l: '모두' },
  ]
  const isDeferred = value === '추후섭취'
  return (
    <div className="flex items-center gap-3 py-3 border-b border-gray-100 last:border-0">
      <div className="w-16 shrink-0">
        <span className="text-sm font-medium text-gray-700 block">{label}</span>
        {menu && <span className="text-xs text-blue-500 leading-tight block">{menu}</span>}
      </div>
      {isDeferred ? (
        <div className="flex-1 flex items-center gap-2">
          <span className="flex-1 text-center text-sm font-medium text-orange-600 bg-orange-50 border border-orange-200 rounded-lg py-2">추후 섭취</span>
          <button type="button" onClick={() => onChange(0)} className="text-xs text-gray-500 underline shrink-0">취소</button>
        </div>
      ) : (
        <div className="flex gap-1.5 flex-1">
          {levels.map(opt => (
            <button key={opt.v} type="button" onClick={() => onChange(opt.v)}
              className={`flex flex-col items-center py-1.5 rounded-xl border-2 transition-colors flex-1 ${
                value === opt.v ? 'border-blue-500 bg-blue-50' : 'border-gray-200 bg-white'}`}>
              <WasteCircle level={opt.v} size={32} />
              <span className="text-xs text-gray-500 mt-0.5" style={{fontSize:'10px'}}>{opt.l}</span>
            </button>
          ))}
        </div>
      )}
      {isSnack && !isDeferred && (
        <button type="button" onClick={() => onChange('추후섭취')}
          className="shrink-0 text-xs px-2 py-1.5 rounded-lg border-2 border-orange-300 text-orange-600 bg-orange-50 hover:bg-orange-100 whitespace-nowrap leading-tight">
          추후<br/>섭취
        </button>
      )}
    </div>
  )
}

// ── 사진 업로드 ──
function PhotoUploader({ day, meal, photoType, label, uploadedUrl, onUploaded, onDeleted }) {
  const cameraRef = useRef(null)
  const galleryRef = useRef(null)
  const [uploading, setUploading] = useState(false)
  const [preview, setPreview] = useState(uploadedUrl || null)
  const [error, setError] = useState('')

  useEffect(() => { setPreview(uploadedUrl || null) }, [uploadedUrl])

  const handleFile = async (file) => {
    if (!file) return
    setError('')
    setPreview(URL.createObjectURL(file))
    setUploading(true)
    try {
      const form = new FormData()
      form.append('day', day)
      form.append('meal', meal)
      form.append('photo_type', photoType)
      form.append('file', file)
      const res = await api.post('/surveys/nutrition/upload-photo', form, {
        headers: { 'Content-Type': 'multipart/form-data' },
      })
      onUploaded(res.data.public_url, res.data.file_name)
    } catch (e) {
      setError(e.response?.data?.detail || '업로드 실패')
      setPreview(uploadedUrl || null)
    } finally { setUploading(false) }
  }

  const handleDelete = async () => {
    if (!window.confirm('사진을 삭제하시겠습니까?')) return
    try {
      const fileName = uploadedUrl?.split('/').pop()
      if (fileName) await api.delete(`/surveys/nutrition/delete-photo?file_name=${encodeURIComponent(fileName)}`)
      setPreview(null)
      onDeleted()
    } catch (e) {
      setError('삭제 실패: ' + (e.response?.data?.detail || e.message))
    }
  }

  return (
    <div className="flex-1 min-w-0">
      <p className="text-sm font-semibold text-gray-700 mb-2 text-center">{label}</p>
      {preview ? (
        <div className="relative">
          <img src={preview} alt={label} className="w-full h-36 object-cover rounded-xl border border-gray-200" />
          {uploading && (
            <div className="absolute inset-0 bg-black/40 rounded-xl flex items-center justify-center">
              <span className="text-white text-sm font-medium">업로드 중...</span>
            </div>
          )}
          {!uploading && (
            <>
              <button type="button" onClick={handleDelete}
                className="absolute top-2 right-2 w-7 h-7 bg-red-500 text-white rounded-full text-sm flex items-center justify-center hover:bg-red-600 shadow">✕</button>
              <div className="absolute bottom-2 left-0 right-0 flex gap-1 justify-center px-2">
                <button type="button" onClick={() => cameraRef.current?.click()}
                  className="flex-1 bg-black/60 text-white text-xs py-1 rounded-lg hover:bg-black/80">📷 재촬영</button>
                <button type="button" onClick={() => galleryRef.current?.click()}
                  className="flex-1 bg-black/60 text-white text-xs py-1 rounded-lg hover:bg-black/80">🖼 앨범</button>
              </div>
            </>
          )}
        </div>
      ) : (
        <div className={`w-full rounded-xl border-2 border-dashed border-gray-300 bg-gray-50 overflow-hidden ${uploading ? 'opacity-50' : ''}`}>
          {uploading ? (
            <div className="h-36 flex items-center justify-center">
              <span className="text-sm text-gray-400">업로드 중...</span>
            </div>
          ) : (
            <>
              <button type="button" onClick={() => cameraRef.current?.click()} disabled={uploading}
                className="w-full py-4 flex flex-col items-center gap-1 hover:bg-blue-50 transition-colors border-b border-gray-200">
                <span className="text-2xl">📷</span>
                <span className="text-sm font-medium text-blue-600">사진 촬영</span>
              </button>
              <button type="button" onClick={() => galleryRef.current?.click()} disabled={uploading}
                className="w-full py-4 flex flex-col items-center gap-1 hover:bg-green-50 transition-colors">
                <span className="text-2xl">🖼️</span>
                <span className="text-sm font-medium text-green-600">앨범에서 선택</span>
              </button>
            </>
          )}
        </div>
      )}
      {error && <p className="text-xs text-red-500 mt-1 text-center">{error}</p>}
      <input ref={cameraRef} type="file" accept="image/*" capture="environment" className="hidden"
        onChange={e => handleFile(e.target.files?.[0])} />
      <input ref={galleryRef} type="file" accept="image/*" className="hidden"
        onChange={e => handleFile(e.target.files?.[0])} />
    </div>
  )
}

// ── 메인 컴포넌트 ──
export default function NutritionSurveyPage() {
  const navigate = useNavigate()
  const [page, setPage] = useState(1)
  const [data, setData] = useState({})
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)
  const [mealPortions, setMealPortions] = useState({})
  const [plateWaste, setPlateWaste] = useState({})
  const [activeDay, setActiveDay] = useState(1)
  const [activeMeal, setActiveMeal] = useState('아침')
  const [photos, setPhotos] = useState({})

  useEffect(() => {
    // 어르신 meal_form 가져오기
    const elderlyId = JSON.parse(localStorage.getItem('user') || '{}')?.elderly_id
    let mealForm = null

    const loadData = async () => {
      // meal_form 조회
      try {
        if (elderlyId) {
          const mfRes = await api.get('/surveys/nutrition/meal-form')
          mealForm = mfRes.data?.meal_form || null
        }
      } catch {}

      // 영양 조사 기존 데이터 로드
      try {
        const r = await api.get('/surveys/nutrition')
        const d = r.data
        if (d && Object.keys(d).length > 0) {
          setData(d)
          try {
            if (d.meal_portions) {
              const existing = typeof d.meal_portions === 'string' ? JSON.parse(d.meal_portions) : d.meal_portions
              // day3~5가 없으면 자동입력으로 채우기
              if (mealForm && (APPLICABLE_MEAL_FORMS.includes(mealForm) || MEAL_FORM_MAP[mealForm])) {
                const hasDay3 = existing['day3'] && Object.keys(existing['day3']).length > 0
                if (!hasDay3) {
                  const auto = getDefaultPortions(normalizeMealForm(mealForm), elderlyId)
                  const merged = { ...auto, ...existing }
                  setMealPortions(merged)
                } else {
                  setMealPortions(existing)
                }
              } else {
                setMealPortions(existing)
              }
            } else if (mealForm && (APPLICABLE_MEAL_FORMS.includes(mealForm) || MEAL_FORM_MAP[mealForm])) {
              // 기존 데이터 없고 meal_form이 적용 대상이면 기본값 자동 세팅
              applyDefaultPortions(normalizeMealForm(mealForm), elderlyId)
            }
            if (d.plate_waste) setPlateWaste(typeof d.plate_waste === 'string' ? JSON.parse(d.plate_waste) : d.plate_waste)
            if (d.photos)      setPhotos(typeof d.photos === 'string' ? JSON.parse(d.photos) : d.photos)
          } catch {}
        } else if (mealForm && (APPLICABLE_MEAL_FORMS.includes(mealForm) || MEAL_FORM_MAP[mealForm])) {
          // 아예 데이터가 없으면 기본값 자동 세팅
          applyDefaultPortions(normalizeMealForm(mealForm), elderlyId)
        }
      } catch {}
    }

    loadData()
  }, [])

  // meal_form에 따라 배식량 기본값 적용 (1~5일차)
  // 배식량 기본값 계산 (순수 함수)
  const getDefaultPortions = (mealForm, elderlyId) => {
    const portions = {}
    const isHS09 = elderlyId === 'HS09'
    const isHS29 = elderlyId === 'HS29'
    ;[1, 2, 3, 4, 5].forEach(day => {
      portions[`day${day}`] = {}
      ;['아침', '점심', '저녁'].forEach(meal => {
        if (isHS09 && day >= 4) {
          const hs09 = DEFAULT_PORTIONS?.[String(day)]?.[meal]?.['일반밥/일반찬_HS09']
          const base = { ...(DEFAULT_PORTIONS?.[String(day)]?.[meal]?.[mealForm] || {}) }
          if (hs09?.['밥/죽']) base['밥/죽'] = hs09['밥/죽']
          if (Object.keys(base).length > 0) portions[`day${day}`][meal] = base
          return
        }
        if (isHS29 && day === 5 && meal === '아침') {
          const hs29 = DEFAULT_PORTIONS?.['5']?.['아침']?.['죽/다진찬_HS29']
          const base = { ...(DEFAULT_PORTIONS?.[String(day)]?.[meal]?.[mealForm] || {}) }
          if (hs29?.['밥/죽']) base['밥/죽'] = hs29['밥/죽']
          if (Object.keys(base).length > 0) portions[`day${day}`][meal] = base
          return
        }
        const defaults = DEFAULT_PORTIONS?.[String(day)]?.[meal]?.[mealForm]
        if (defaults) portions[`day${day}`][meal] = { ...defaults }
      })
    })
    return portions
  }

  const applyDefaultPortions = (mealForm, elderlyId) => {
    setMealPortions(getDefaultPortions(mealForm, elderlyId))
  }

  const photoKey = (day, meal, type) => `day${day}_${meal}_${type}`

  // 현재 일차의 끼니별 음식 목록 가져오기
  // 어르신 ID
  const currentElderlyId = JSON.parse(localStorage.getItem('user') || '{}')?.elderly_id || ''

  // 4일차 간식2: HS 번호 기반으로 푸딩 종류 결정
  const getSnack2Day4 = () => {
    const num = parseInt(currentElderlyId.replace('HS', ''), 10)
    if (num >= 1 && num <= 18) return [{ food: '간식', menu: '파인애플맛 푸딩' }]
    if (num >= 19 && num <= 37) return [{ food: '간식', menu: '망고맛 푸딩' }]
    if (num >= 38 && num <= 52) return [{ food: '간식', menu: '멜론맛 푸딩' }]
    return [{ food: '간식', menu: '푸딩' }]
  }

  const getFoods = (day, meal) => {
    if (day === 4 && meal === '간식2') return getSnack2Day4()
    return MEAL_FOODS_BY_DAY[day]?.[meal] || MEAL_FOODS_BY_DAY[3][meal] || []
  }

  const getGram = (day, meal, food) => {
    const stored = mealPortions[`day${day}`]?.[meal]?.[food]
    if (stored !== undefined && stored !== null) return stored
    // 간식은 SNACK_DEFAULT_PORTIONS에서 기본값
    if (meal === '간식1' || meal === '간식2') {
      return SNACK_DEFAULT_PORTIONS?.[day]?.[meal]?.[food] ?? ''
    }
    return ''
  }
  const setGram = (day, meal, food, val) =>
    setMealPortions(prev => ({ ...prev, [`day${day}`]: { ...(prev[`day${day}`] || {}), [meal]: { ...(prev[`day${day}`]?.[meal] || {}), [food]: val } } }))

  const getWaste = (day, meal, food) => plateWaste[`day${day}`]?.[meal]?.[food] ?? 0
  const setWaste = (day, meal, food, val) =>
    setPlateWaste(prev => ({ ...prev, [`day${day}`]: { ...(prev[`day${day}`] || {}), [meal]: { ...(prev[`day${day}`]?.[meal] || {}), [food]: val } } }))

  const handleNext = async () => {
    if (page < TOTAL_PAGES) { setPage(p => p + 1); setActiveDay(1); setActiveMeal('아침'); window.scrollTo(0, 0) }
    else await handleSubmit()
  }

  const handleSubmit = async () => {
    setSaving(true)
    try {
      // 완료된 일차 계산
      const completedDays = [1,2,3,4,5].filter(day => {
        const mp = mealPortions[`day${day}`] || {}
        const pw = plateWaste[`day${day}`] || {}
        return Object.keys(mp).length > 0 || Object.keys(pw).length > 0
      })
      await api.post('/surveys/nutrition', {
        data: { ...data, meal_portions: mealPortions, plate_waste: plateWaste, photos, completed_days: completedDays }
      })
      setSaved(true)
      setTimeout(() => navigate('/dashboard'), 1500)
    } catch (e) {
      alert('저장 중 오류: ' + (e.response?.data?.detail || e.message))
    } finally { setSaving(false) }
  }

  if (saved) return (
    <div className="min-h-screen bg-gray-50 flex items-center justify-center">
      <div className="card text-center p-10">
        <div className="text-5xl mb-4">✅</div>
        <p className="text-lg font-semibold">영양 조사표가 저장되었습니다!</p>
        <p className="text-sm text-gray-500 mt-2">대시보드로 이동합니다...</p>
      </div>
    </div>
  )

  const countPhotos = (day) =>
    MEALS.reduce((n, meal) => {
      if (photos[photoKey(day, meal, 'before')]?.url) n++
      if (photos[photoKey(day, meal, 'after')]?.url) n++
      return n
    }, 0)

  const DayTabs = ({ showPhotoCount = false }) => (
    <div className="flex gap-2 mb-4 flex-wrap">
      {DAYS.map(d => {
        const cnt = showPhotoCount ? countPhotos(d) : null
        const total = MEALS.length * 2
        return (
          <button key={d} type="button" onClick={() => setActiveDay(d)}
            className={`px-4 py-2 rounded-xl text-sm font-medium transition-colors ${
              activeDay === d ? 'bg-blue-600 text-white shadow' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'}`}>
            {d}일차
            {showPhotoCount && (
              <span className={`ml-1.5 text-xs ${activeDay === d ? 'text-blue-100' : cnt === total ? 'text-green-600 font-bold' : 'text-gray-400'}`}>
                {cnt}/{total}
              </span>
            )}
          </button>
        )
      })}
    </div>
  )

  return (
    <SurveyLayout
      title="영양 조사표" icon="🥗"
      page={page} totalPages={TOTAL_PAGES}
      onPrev={() => { setPage(p => p - 1); setActiveDay(1); window.scrollTo(0,0) }}
      onNext={handleNext}
      onDashboard={() => navigate('/dashboard')}
      nextLabel={saving ? '저장 중...' : undefined}
    >
      {/* ── 1페이지: 배식량 ── */}
      {page === 1 && (
        <div>
          <h2 className="section-title">끼니별 음식 배식량 입력</h2>
          <InfoBox>📝 5일 동안 각 끼니에서 제공한 음식의 무게(g)를 입력해주세요.</InfoBox>
          <DayTabs />
          <div className="flex gap-1.5 mb-4 flex-wrap">
            {MEALS.map(meal => (
              <button key={meal} type="button" onClick={() => setActiveMeal(meal)}
                className={`px-3 py-1.5 rounded-lg text-sm font-medium transition-colors ${
                  activeMeal === meal ? 'bg-blue-600 text-white' : 'bg-gray-100 text-gray-600 hover:bg-gray-200'
                }`}>{meal}</button>
            ))}
          </div>
          <div className="bg-gray-50 rounded-xl px-4 py-2">
            <p className="text-xs text-gray-400 mb-1 pt-2">{activeDay}일차 · {activeMeal}</p>
            {getFoods(activeDay, activeMeal).map(({ food, menu }) => (
              <GramInput key={food} label={food} menu={menu}
                isSnack={activeMeal === '간식1' || activeMeal === '간식2'}
                value={getGram(activeDay, activeMeal, food)}
                onChange={v => setGram(activeDay, activeMeal, food, v)} />
            ))}
          </div>
        </div>
      )}

      {/* ── 2페이지: 잔반량 + 사진 ── */}
      {page === 2 && (
        <div>
          <h2 className="section-title">음식별 잔반량 + 식사 사진</h2>
          <InfoBox>
            ① 원형 그림으로 잔반량을 선택하고<br />
            ② 각 끼니의 <strong>식전·식후 사진</strong>을 업로드해주세요.
          </InfoBox>
          <div className="flex justify-around mb-4 p-3 bg-gray-50 rounded-xl">
            {[{l:0,t:'다 먹음'},{l:1,t:'25%'},{l:2,t:'50%'},{l:3,t:'75%'},{l:4,t:'모두'}].map(item => (
              <div key={item.l} className="text-center">
                <WasteCircle level={item.l} size={44} />
                <p className="text-xs text-gray-500 mt-1">{item.t}</p>
              </div>
            ))}
          </div>
          <DayTabs showPhotoCount />
          {MEALS.map(meal => (
            <div key={meal} className="mb-6 border border-gray-100 rounded-2xl p-4 bg-white shadow-sm">
              <h3 className="text-base font-bold text-blue-700 mb-4 border-b border-blue-100 pb-2">{meal}</h3>
              <div className="mb-5 bg-gray-50 rounded-xl px-3 py-1">
                {getFoods(activeDay, meal)
                  .filter(({ food }) => {
                    // 김치1/김치2는 배식량에 값이 있을 때만 표시
                    if (food === '김치1' || food === '김치2') {
                      const portionVal = getGram(activeDay, meal, food)
                      return portionVal !== '' && portionVal !== null && portionVal !== undefined
                    }
                    return true
                  })
                  .map(({ food, menu }) => (
                  <WasteSelector key={food} label={food} menu={menu}
                    isSnack={meal === '간식1' || meal === '간식2'}
                    value={getWaste(activeDay, meal, food)}
                    onChange={v => setWaste(activeDay, meal, food, v)} />
                ))}
              </div>
              <div className="grid grid-cols-2 gap-3">
                {['before', 'after'].map(type => (
                  <PhotoUploader key={type} day={activeDay} meal={meal} photoType={type}
                    label={type === 'before' ? '🍽️ 식전' : '🥣 식후'}
                    uploadedUrl={photos[photoKey(activeDay, meal, type)]?.url}
                    onUploaded={(url, fileName) =>
                      setPhotos(prev => ({ ...prev, [photoKey(activeDay, meal, type)]: { url, fileName } }))
                    }
                    onDeleted={() =>
                      setPhotos(prev => { const n = {...prev}; delete n[photoKey(activeDay, meal, type)]; return n })
                    }
                  />
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      {/* ── 3페이지: 최종 확인 ── */}
      {page === 3 && (
        <div>
          <h2 className="section-title">최종 확인</h2>
          <div className="mb-4">
            <p className="text-sm font-medium text-gray-700 mb-3">📸 사진 업로드 현황</p>
            <div className="grid grid-cols-5 gap-2">
              {DAYS.map(d => {
                const cnt = countPhotos(d)
                const total = MEALS.length * 2
                const done = cnt === total
                return (
                  <div key={d} className={`text-center p-3 rounded-xl border-2 ${done ? 'border-green-300 bg-green-50' : 'border-gray-200 bg-gray-50'}`}>
                    <p className="text-xs font-medium text-gray-600">{d}일차</p>
                    <p className={`text-xl font-bold mt-1 ${done ? 'text-green-600' : 'text-gray-400'}`}>{cnt}</p>
                    <p className="text-xs text-gray-400">/{total}장</p>
                  </div>
                )
              })}
            </div>
          </div>
          <Divider label="저장" />
          <InfoBox type="success">✅ 제출 버튼을 눌러 저장하세요.</InfoBox>
        </div>
      )}
    </SurveyLayout>
  )
}